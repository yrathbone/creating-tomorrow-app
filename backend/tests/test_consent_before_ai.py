"""Nothing is sent to the AI service until the person has consented (finding V-02).

Consent creates the Career Profile (POST /consent). Before this check, /resume-start, /resume-discover and /job-discover
reached the AI first. Here a signed-in person who has NOT consented calls every AI route; each must answer 404 ("consent
first") without constructing the AI client at all. The real token check is used (see test_ownership); the AI is a recorder.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import os
from unittest import mock

import abuse_guard
from tests.test_ownership import OwnershipTestCase

JOB_TEXT = "Senior analyst wanted. Requires five years of experience with reporting, budgeting and stakeholder communication."
FILE = {"resume_file": ("resume.txt", b"Jane Doe. Cashier at a store for five years.", "text/plain")}

# route -> (request kwargs, the AI-calling function the handler would use once allowed)
AI_ROUTES = {
    "/skills-tidy-suggest": ({}, "suggest_skill_keywords"),
    "/resume-start": ({"files": FILE}, "start_resume_review"),
    "/resume-discover": ({"json": {"resume_data": {"roles": []}}}, "discover"),
    "/job-compare": ({"json": {"job_description": JOB_TEXT}}, "compare_to_job"),
    "/job-keyword-check": ({"json": {"job_description": JOB_TEXT}}, "keyword_check"),
    "/job-discover": ({"json": {"resume_data": {"roles": []}}}, "discover"),
    "/job-build-resume": ({"json": {"job_description": JOB_TEXT, "name": "N", "contact": "c@example.com"}}, "build_checked_resume"),
    "/build-general-resume": ({"json": {"name": "N", "contact": "c@example.com"}}, "build_general_resume"),
    "/skill-scan": ({}, "start_skill_scan"),
}


class ConsentBeforeAI(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()

    def test_the_list_covers_every_route_that_uses_the_guard(self):
        from career.routes import router
        guarded = {r.path for r in router.routes if any(d.call is abuse_guard.user_ai_guard for d in r.dependant.dependencies)}
        self.assertEqual(guarded, set(AI_ROUTES), "a new AI route must be added to this test (and must use AI_ROUTE_GUARDS)")

    def test_every_ai_route_refuses_a_person_who_has_not_consented_before_any_ai_call(self):
        for path, (kwargs, ai_function) in AI_ROUTES.items():
            with self.subTest(route=path), mock.patch("anthropic.Anthropic") as client, \
                    mock.patch(f"career.routes.{ai_function}") as ai, mock.patch("career.routes.extract_text_async") as extract:
                res = self.call("POST", path, self.a, **kwargs)  # signed in, never consented
                self.assertEqual(res.status_code, 404, f"{path}: {res.text}")
                self.assertIn("consent", res.json()["detail"].lower())
                ai.assert_not_called()
                client.assert_not_called()
                extract.assert_not_called()
        self.assertEqual(abuse_guard.IN_FLIGHT.count, 0, "a refused request must give back its AI slot")

    def test_a_refused_request_still_counts_toward_the_per_account_rate_limit(self):
        with mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "2/60"}), mock.patch("career.routes.compare_to_job"):
            codes = [self.call("POST", "/job-compare", self.a, json={"job_description": JOB_TEXT}).status_code for _ in range(3)]
        self.assertEqual(codes, [404, 404, 429])

    def test_after_consent_the_same_routes_reach_the_ai(self):
        self.onboard(self.a)
        with mock.patch("career.routes.discover", return_value={"stage": "questions", "questions": []}) as ai:
            res = self.call("POST", "/job-discover", self.a, json={"resume_data": {"roles": []}})
            self.assertEqual(res.status_code, 200, res.text)
            ai.assert_called_once()
        resume = {"name": "N", "contact": "c", "summary": "", "skills": [], "experience": [], "education": []}
        with mock.patch("career.routes.build_general_resume", return_value={"resume_data": dict(resume)}) as ai:
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "N", "contact": "c@example.com"})
            self.assertEqual(res.status_code, 200, res.text)
            ai.assert_called_once()

    def test_a_consented_person_is_unaffected_by_someone_elses_missing_consent(self):
        self.onboard(self.a)  # A consented, B never did
        with mock.patch("career.routes.discover", return_value={"stage": "questions", "questions": []}) as ai:
            self.assertEqual(self.call("POST", "/job-discover", self.b, json={"resume_data": {}}).status_code, 404)
            ai.assert_not_called()
            self.assertEqual(self.call("POST", "/job-discover", self.a, json={"resume_data": {}}).status_code, 200)
