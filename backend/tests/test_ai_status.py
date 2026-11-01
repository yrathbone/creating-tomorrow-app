"""When the AI service refuses or is unavailable, people are told the truth and lose nothing (proposal P7).

The AI service is replaced by stand-ins that raise errors shaped like Anthropic's documented ones (see ai_status.py), so
nothing here spends anything or touches the network.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import io
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import abuse_guard
import ai_status
import main
from career.job_match import JobMatchError
from coach import CoachError
from models import ScanHistory
from tests.test_ownership import JOB_TEXT, OwnershipTestCase

SPEND_LIMIT_400 = {"type": "error", "error": {"type": "invalid_request_error", "message": "You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC."}}
TIER_CAP_429 = {"type": "error", "error": {"type": "rate_limit_error", "message": "You have reached your API usage limits.", "details": {"error_code": "enforced_spend_limit_reached"}}}
RATE_429 = {"type": "error", "error": {"type": "rate_limit_error", "message": "Number of request tokens has exceeded your per-minute rate limit"}}
BILLING_402 = {"type": "error", "error": {"type": "billing_error", "message": "There is an issue with your billing."}}
CREDIT_400 = {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API."}}
OVERLOADED_529 = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
BAD_KEY_401 = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
OTHER_400 = {"type": "error", "error": {"type": "invalid_request_error", "message": "messages: text content blocks must be non-empty"}}

FRIENDLY = "We couldn't complete this right now. Please try again."


class FakeAPIError(Exception):
    def __init__(self, status, body, headers=None):
        super().__init__(f"fake {status}")
        self.status_code, self.body = status, body
        self.response = type("R", (), {"headers": headers or {}})()


class APIConnectionError(Exception):  # same class name as the SDK's, no status code
    pass


def raising(error_class, provider_error):
    """What the tool modules do: raise their own friendly error `from` the provider's exception."""
    def fn(*args, **kwargs):
        try:
            raise provider_error
        except Exception as cause:
            raise error_class(FRIENDLY) from cause
    return fn


def tool_error(error_class, provider_error):
    try:
        raising(error_class, provider_error)()
    except error_class as e:
        return e


class Classifier(unittest.TestCase):
    def test_documented_shapes_map_to_the_right_kind(self):
        table = [
            (FakeAPIError(400, SPEND_LIMIT_400), "spend_limit"),
            (FakeAPIError(429, TIER_CAP_429), "spend_limit"),
            (FakeAPIError(402, BILLING_402), "billing"),
            (FakeAPIError(400, CREDIT_400), "billing"),
            (FakeAPIError(429, RATE_429), "rate_limited"),
            (FakeAPIError(529, OVERLOADED_529), "busy"),
            (FakeAPIError(500, {}), "busy"),
            (FakeAPIError(504, {}), "busy"),
            (APIConnectionError("boom"), "busy"),
            (FakeAPIError(401, BAD_KEY_401), "config"),
            (FakeAPIError(403, {}), "config"),
            (FakeAPIError(400, OTHER_400), "other"),
            (ValueError("no status at all"), "other"),
        ]
        for error, expected in table:
            with self.subTest(error=repr(error)):
                self.assertEqual(ai_status.classify_provider_error(error), expected)


    def test_the_real_sdk_exception_classes_are_classified_the_same_way(self):
        import anthropic
        import httpx
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        client = anthropic.Anthropic(api_key="not-a-real-key")  # never used to call anything
        for status, body, expected in ((400, SPEND_LIMIT_400, "spend_limit"), (429, TIER_CAP_429, "spend_limit"), (529, OVERLOADED_529, "busy"), (401, BAD_KEY_401, "config")):
            with self.subTest(status=status):
                response = httpx.Response(status, json=body, request=request)
                error = client._make_status_error("provider error", body=response.json(), response=response)
                self.assertEqual(ai_status.classify_provider_error(error), expected)
        self.assertEqual(ai_status.classify_provider_error(anthropic.APIConnectionError(request=request)), "busy")
        self.assertEqual(ai_status.classify_provider_error(anthropic.APITimeoutError(request=request)), "busy")


class Failure(unittest.TestCase):
    def setUp(self):
        ai_status.reset()
        self.addCleanup(ai_status.reset)

    def test_a_spent_allowance_is_a_503_that_says_so_and_names_the_date(self):
        exc = ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400)))
        self.assertEqual(exc.status_code, 503)
        self.assertIn("nothing was lost", exc.detail)
        self.assertIn("2026-12-01", exc.detail)
        self.assertNotIn("try again", exc.detail.lower())
        self.assertEqual(exc.headers["X-AI-Status"], "paused")
        self.assertIsNotNone(ai_status.pause_state())

    def test_a_busy_service_is_a_503_with_a_wait_hint_and_does_not_pause(self):
        exc = ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(529, OVERLOADED_529)))
        self.assertEqual((exc.status_code, exc.headers["X-AI-Status"]), (503, "busy"))
        self.assertIn("Your work is still here", exc.detail)
        self.assertIsNone(ai_status.pause_state())

    def test_provider_retry_after_is_passed_on(self):
        exc = ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(429, RATE_429, {"retry-after": "42"})))
        self.assertEqual(exc.headers["Retry-After"], "42")

    def test_a_refused_key_is_unavailable_not_try_again_and_never_pauses(self):
        exc = ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(401, BAD_KEY_401)))
        self.assertEqual(exc.status_code, 503)
        self.assertNotIn("401", exc.detail)
        self.assertIsNone(ai_status.pause_state())

    def test_anything_unrecognised_keeps_the_old_502_and_wording(self):
        for error in (tool_error(JobMatchError, FakeAPIError(400, OTHER_400)), JobMatchError(FRIENDLY)):
            exc = ai_status.ai_failure(error)
            self.assertEqual(exc.status_code, 502)
            self.assertEqual(exc.detail, FRIENDLY)

    def test_the_pause_ends_after_the_window(self):
        now = [1000.0]
        with mock.patch.object(ai_status, "_clock", lambda: now[0]):
            ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(402, BILLING_402)))
            self.assertIsNotNone(ai_status.pause_state())
            now[0] += ai_status.DEFAULT_PAUSE_SECONDS + 1
            self.assertIsNone(ai_status.pause_state())

    def test_the_pause_length_can_be_set_with_an_environment_setting(self):
        with mock.patch.dict(os.environ, {"AI_PAUSE_SECONDS": "60"}):
            self.assertEqual(ai_status._pause_seconds(), 60)
        with mock.patch.dict(os.environ, {"AI_PAUSE_SECONDS": "nonsense"}):
            self.assertEqual(ai_status._pause_seconds(), ai_status.DEFAULT_PAUSE_SECONDS)


class SignedInRoutes(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()
        ai_status.reset()
        self.addCleanup(ai_status.reset)
        self.onboard(self.a)

    def compare(self):
        return self.call("POST", "/job-compare", self.a, json={"job_description": JOB_TEXT})

    def test_after_a_spend_limit_error_people_get_the_honest_message_and_no_more_calls_reach_the_ai(self):
        stand_in = mock.Mock(side_effect=raising(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400)))
        with mock.patch("career.routes.compare_to_job", stand_in):
            first = self.compare()
            self.assertEqual(first.status_code, 503, first.text)
            self.assertIn("nothing was lost", first.json()["detail"])
            self.assertEqual(first.headers["X-AI-Status"], "paused")
            second = self.compare()
            third = self.call("POST", "/skill-scan", self.a)
            self.assertEqual((second.status_code, third.status_code), (503, 503))
            self.assertEqual(stand_in.call_count, 1, "while paused, the AI service is not contacted again")
        self.assertEqual(abuse_guard.IN_FLIGHT.count, 0)

    def test_everything_that_needs_no_ai_keeps_working_while_paused(self):
        with mock.patch("career.routes.compare_to_job", side_effect=raising(JobMatchError, FakeAPIError(402, BILLING_402))):
            self.compare()
        self.assertIsNotNone(ai_status.pause_state())
        made = self.call("POST", "/experiences", self.a, json={"title": "T", "organization": "O"})
        self.assertEqual(made.status_code, 200)
        self.assertEqual(self.call("GET", "/experiences", self.a).status_code, 200)
        self.assertEqual(self.call("GET", "/export", self.a).status_code, 200)

    def test_the_ai_is_tried_again_once_the_pause_ends(self):
        now = [5000.0]
        stand_in = mock.Mock(side_effect=raising(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400)))
        with mock.patch.object(ai_status, "_clock", lambda: now[0]), mock.patch("career.routes.compare_to_job", stand_in):
            self.compare()
            now[0] += ai_status.DEFAULT_PAUSE_SECONDS + 1
            self.compare()
        self.assertEqual(stand_in.call_count, 2)

    def test_a_busy_service_is_reported_as_busy_and_the_next_request_still_goes_through(self):
        stand_in = mock.Mock(side_effect=raising(JobMatchError, FakeAPIError(529, OVERLOADED_529)))
        with mock.patch("career.routes.compare_to_job", stand_in):
            res = self.compare()
            self.compare()
        self.assertEqual((res.status_code, res.headers["X-AI-Status"]), (503, "busy"))
        self.assertEqual(stand_in.call_count, 2)

    def test_interview_answers_are_saved_before_the_build_call_so_a_failure_loses_nothing(self):
        pid = self.profile_id_for("aaaaaaaa-0000-4000-8000-00000000000a")
        with self.Session() as s:
            scan = ScanHistory(career_profile_id=pid, scan_type="job_comparison", job_title="J", summary_text="s", result_data={"qa_history": []})
            s.add(scan)
            s.commit()
            scan_id = scan.id
        answers = [{"question": "Did you manage a budget?", "answer": "yes, $50k"}]
        body = {"job_description": JOB_TEXT, "name": "N", "contact": "c@example.com", "scan_history_id": scan_id, "qa_history": answers}
        with mock.patch("career.routes.build_checked_resume", side_effect=raising(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400))):
            res = self.call("POST", "/job-build-resume", self.a, json=body)
        self.assertEqual(res.status_code, 503)
        with self.Session() as s:
            self.assertEqual(s.get(ScanHistory, scan_id).result_data["qa_history"], answers)

    def test_a_retry_sent_without_answers_does_not_wipe_the_saved_ones(self):
        pid = self.profile_id_for("aaaaaaaa-0000-4000-8000-00000000000a")
        answers = [{"question": "Did you manage a budget?", "answer": "yes, $50k"}]
        with self.Session() as s:
            scan = ScanHistory(career_profile_id=pid, scan_type="job_comparison", job_title="J", summary_text="s", result_data={"qa_history": answers})
            s.add(scan)
            s.commit()
            scan_id = scan.id
        body = {"job_description": JOB_TEXT, "name": "N", "contact": "c@example.com", "scan_history_id": scan_id, "qa_history": []}
        with mock.patch("career.routes.build_checked_resume", side_effect=raising(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400))):
            self.assertEqual(self.call("POST", "/job-build-resume", self.a, json=body).status_code, 503)
        with self.Session() as s:
            self.assertEqual(s.get(ScanHistory, scan_id).result_data["qa_history"], answers)
        newer = [{"question": "Did you lead a team?", "answer": "yes"}]
        ai_status.reset()  # the first failure paused the AI; let the next request reach the route
        with mock.patch("career.routes.build_checked_resume", side_effect=raising(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400))):
            self.call("POST", "/job-build-resume", self.a, json=dict(body, qa_history=newer))
        with self.Session() as s:
            self.assertEqual(s.get(ScanHistory, scan_id).result_data["qa_history"], newer, "new answers still replace old ones")


class HealthAndPublicTools(unittest.TestCase):
    def setUp(self):
        ai_status.reset()
        abuse_guard.reset()
        self.addCleanup(ai_status.reset)
        self.client = TestClient(main.app)

    def test_health_reports_the_pause_and_the_monitor_endpoint_goes_red(self):
        with mock.patch.object(main, "check_ai_key", lambda *a, **k: "ok"):
            self.assertFalse(self.client.get("/api/health").json()["ai_paused"])
            self.assertEqual(self.client.get("/api/health/ai").status_code, 200)
            ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(400, SPEND_LIMIT_400)))
            self.assertTrue(self.client.get("/api/health").json()["ai_paused"])
            res = self.client.get("/api/health/ai")
            self.assertEqual(res.status_code, 503)
            self.assertEqual(res.json(), {"ai_key": "ok", "paused": "spend_limit"})
            self.assertEqual(self.client.head("/api/health/ai").status_code, 503)

    def test_public_tools_answer_at_once_while_paused_and_never_reach_the_tool(self):
        with mock.patch.object(main, "analyze") as analyze, mock.patch("turnstile.enabled", return_value=False):
            ai_status.ai_failure(tool_error(JobMatchError, FakeAPIError(402, BILLING_402)))
            res = self.client.post("/api/analyze", files={"resume_file": ("r.txt", io.BytesIO(b"Jane Doe, cashier."), "text/plain")}, data={"job_posting": JOB_TEXT})
            self.assertEqual(res.status_code, 503, res.text)
            self.assertIn("nothing was lost", res.json()["detail"])
            analyze.assert_not_called()

    def test_a_public_tool_failure_with_a_spent_allowance_pauses_everything(self):
        stand_in = mock.Mock(side_effect=raising(CoachError, FakeAPIError(400, SPEND_LIMIT_400)))
        with mock.patch.object(main, "analyze", stand_in), mock.patch("turnstile.enabled", return_value=False):
            def files():
                return {"resume_file": ("r.txt", io.BytesIO(b"Jane Doe, cashier."), "text/plain")}
            first = self.client.post("/api/analyze", files=files(), data={"job_posting": JOB_TEXT})
            second = self.client.post("/api/analyze", files=files(), data={"job_posting": JOB_TEXT})
        self.assertEqual((first.status_code, second.status_code), (503, 503))
        self.assertEqual(stand_in.call_count, 1)


if __name__ == "__main__":
    unittest.main()
