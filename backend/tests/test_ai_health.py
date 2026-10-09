"""The AI-key health check: is the key actually accepted, not merely set."""
import contextlib
import io
import os
import threading
import time
import unittest
from unittest import mock

import anthropic
try:  # the pinned AI library uses httpx2; older setups still have httpx
    import httpx2 as httpx
except ImportError:
    import httpx
from fastapi.testclient import TestClient

import ai_health
import main

SECRET = "sk-ant-api03-THIS-MUST-NEVER-APPEAR-IN-ANY-OUTPUT"


def status_error(cls, status):
    response = httpx.Response(status, request=httpx.Request("GET", "https://api.anthropic.com/v1/models"), headers={"request-id": "req_x"})
    return cls("provider text", response=response, body={"error": {"type": "authentication_error", "message": "invalid x-api-key"}})


class FakeClient:
    """Stands in for anthropic.Anthropic: only the free models list exists; anything that would spend credit is missing."""
    def __init__(self, behaviour, calls):
        self.models = self
        self._behaviour, self._calls = behaviour, calls

    def list(self, **kwargs):
        self._calls.append(kwargs)
        if isinstance(self._behaviour, Exception):
            raise self._behaviour
        return []


def probe_with(behaviour, key=SECRET):
    calls = []
    with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": key} if key else {}, clear=False), \
         mock.patch.object(ai_health.anthropic, "Anthropic", lambda **kw: FakeClient(behaviour, calls)):
        if not key:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = ai_health.probe_ai_key()
    return status, calls, out.getvalue()


class ProbeTests(unittest.TestCase):
    def test_an_accepted_key_is_ok_and_only_the_free_models_list_is_called(self):
        status, calls, _ = probe_with(None)
        self.assertEqual(status, "ok")
        self.assertEqual(calls, [{"limit": 1}])

    def test_a_refused_key_is_rejected(self):
        for cls, code in ((anthropic.AuthenticationError, 401), (anthropic.PermissionDeniedError, 403)):
            with self.subTest(code):
                status, _, log = probe_with(status_error(cls, code))
                self.assertEqual(status, "rejected")
                self.assertIn("status=%d" % code, log)

    def test_network_trouble_is_unreachable(self):
        request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        self.assertEqual(probe_with(anthropic.APIConnectionError(request=request))[0], "unreachable")
        self.assertEqual(probe_with(anthropic.APITimeoutError(request=request))[0], "unreachable")

    def test_a_busy_service_is_an_error_not_a_rejected_key(self):
        self.assertEqual(probe_with(status_error(anthropic.RateLimitError, 429))[0], "error")
        self.assertEqual(probe_with(status_error(anthropic.InternalServerError, 500))[0], "error")

    def test_an_unexpected_failure_never_escapes(self):
        status, _, log = probe_with(RuntimeError("boom"))
        self.assertEqual(status, "error")
        self.assertIn("RuntimeError", log)

    def test_no_key_set_means_not_configured_and_no_call_is_made(self):
        status, calls, _ = probe_with(None, key=None)
        self.assertEqual(status, "not_configured")
        self.assertEqual(calls, [])

    def test_the_key_is_never_written_to_the_log(self):
        for behaviour in (status_error(anthropic.AuthenticationError, 401), RuntimeError("x"), None):
            _, _, log = probe_with(behaviour)
            self.assertNotIn(SECRET, log)


class RememberingTests(unittest.TestCase):
    def setUp(self):
        ai_health.forget()
        self.now = [1000.0]
        self.calls = []

    def check(self, answer, **kw):
        def probe():
            self.calls.append(answer)
            return answer
        return ai_health.check_ai_key(probe=probe, clock=lambda: self.now[0], **kw)

    def test_a_good_answer_is_reused_for_five_minutes(self):
        self.assertEqual(self.check("ok"), "ok")
        self.now[0] += 299
        self.check("ok")
        self.assertEqual(len(self.calls), 1)
        self.now[0] += 2
        self.check("ok")
        self.assertEqual(len(self.calls), 2)

    def test_a_bad_answer_is_rechecked_sooner_so_a_fixed_key_shows_quickly(self):
        self.assertEqual(self.check("rejected"), "rejected")
        self.now[0] += 29
        self.check("ok")
        self.assertEqual(len(self.calls), 1)
        self.now[0] += 2
        self.assertEqual(self.check("ok"), "ok")
        self.assertEqual(len(self.calls), 2)

    def test_force_ignores_what_is_remembered(self):
        self.check("ok")
        self.assertEqual(self.check("rejected", force=True), "rejected")
        self.assertEqual(len(self.calls), 2)

    def test_many_quick_requests_make_one_call(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.check("ok"))) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, ["ok"] * 12)
        self.assertEqual(len(self.calls), 1)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        ai_health.forget()
        self.client = TestClient(main.app)

    def tearDown(self):
        ai_health.forget()

    def get(self, path, status):
        with mock.patch.object(main, "check_ai_key", lambda: status), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}):
            return self.client.get(path)

    def test_health_always_answers_200_and_reports_the_key(self):
        for status in ("ok", "rejected", "unreachable", "error", "not_configured"):
            with self.subTest(status):
                res = self.get("/api/health", status)
                self.assertEqual(res.status_code, 200)
                body = res.json()
                self.assertEqual(body["ai_key"], status)
                self.assertEqual(body["status"], "ok")
                self.assertIn("api_key_configured", body)
                self.assertIn("database", body)

    def test_the_health_page_says_how_visitors_are_told_apart_without_showing_any_address(self):
        with mock.patch.object(main, "check_ai_key", lambda: "ok"):
            plain = self.client.get("/api/health").json()
            via_cloudflare = self.client.get("/api/health", headers={"CF-Ray": "abc-ORD", "CF-Connecting-IP": "203.0.113.9"})
        self.assertEqual(plain["visitor_address_source"], "direct")
        self.assertEqual(via_cloudflare.json()["visitor_address_source"], "cloudflare")
        self.assertNotIn("203.0.113.9", via_cloudflare.text)

    def test_the_monitor_endpoint_is_200_only_when_the_key_is_accepted(self):
        self.assertEqual(self.get("/api/health/ai", "ok").status_code, 200)
        self.assertEqual(self.get("/api/health/ai", "ok").json(), {"ai_key": "ok"})
        for bad in ("rejected", "unreachable", "error", "not_configured"):
            with self.subTest(bad):
                res = self.get("/api/health/ai", bad)
                self.assertEqual(res.status_code, 503)
                self.assertEqual(res.json(), {"ai_key": bad})

    def test_no_response_ever_contains_the_key(self):
        for path in ("/api/health", "/api/health/ai"):
            for status in ("ok", "rejected"):
                self.assertNotIn(SECRET, self.get(path, status).text)

    def test_a_refused_key_shows_on_the_real_page_through_the_real_check(self):
        ai_health.forget()
        request_status = status_error(anthropic.AuthenticationError, 401)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET}), \
             mock.patch.object(ai_health.anthropic, "Anthropic", lambda **kw: FakeClient(request_status, [])), \
             contextlib.redirect_stdout(io.StringIO()):
            res = self.client.get("/api/health")
            res_ai = self.client.get("/api/health/ai")
        self.assertEqual(res.json()["ai_key"], "rejected")
        self.assertEqual(res_ai.status_code, 503)


class StartupTests(unittest.TestCase):
    def test_starting_the_server_writes_one_line_about_the_key(self):
        out = io.StringIO()
        with mock.patch.object(ai_health, "check_ai_key", lambda force=False: "rejected"), contextlib.redirect_stdout(out):
            ai_health.log_at_startup()
            for t in threading.enumerate():
                if t.name == "ai-key-startup-check":
                    t.join(timeout=3)
        self.assertIn("[startup] AI key check: rejected", out.getvalue())

    def test_the_app_runs_that_check_when_it_starts(self):
        ran = []
        with mock.patch.object(main, "log_at_startup", lambda: ran.append(True)):
            with TestClient(main.app):
                pass
        self.assertEqual(ran, [True])

    def test_a_server_with_no_key_still_starts(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            ai_health.forget()
            with contextlib.redirect_stdout(io.StringIO()):
                with TestClient(main.app) as client:
                    time.sleep(0.2)
                    self.assertEqual(client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
