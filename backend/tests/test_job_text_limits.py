"""One length rule for the pasted job posting on every route that sends it to the paid AI service.

Before, /job-build-resume (up to four paid calls per build) had no limit at all, unlike /job-compare and /job-keyword-check.
The AI functions are replaced with a recording stand-in, so these tests spend nothing and also prove a refused request
never reaches the AI service.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import os
from unittest import mock

import abuse_guard
from career.routes import MAX_JOB_DESCRIPTION_CHARS, MIN_JOB_DESCRIPTION_CHARS
from tests.test_ownership import OwnershipTestCase

ROUTES = {
    # route: (function in career.routes that calls the AI, extra JSON fields the route needs)
    "/job-compare": ("compare_to_job", {}),
    "/job-keyword-check": ("keyword_check", {}),
    "/job-build-resume": ("build_checked_resume", {"name": "N", "contact": "c@example.com"}),
}


class JobTextLimits(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        # these tests make many calls in a row; give them their own generous allowance instead of the shared per-minute one
        env = mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"})
        env.start()
        self.addCleanup(env.stop)
        limiter = mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())
        limiter.start()
        self.addCleanup(limiter.stop)
        self.onboard(self.a)

    def post(self, path, text):
        extra = ROUTES[path][1]
        return self.call("POST", path, self.a, json={"job_description": text, **extra})

    def test_text_outside_the_limits_is_refused_and_never_reaches_the_ai(self):
        too_short = "x" * (MIN_JOB_DESCRIPTION_CHARS - 1)
        too_long = "x" * (MAX_JOB_DESCRIPTION_CHARS + 1)
        for path, (ai_function, _) in ROUTES.items():
            for label, text in (("empty", ""), ("blank", "   \n  "), ("too short", too_short), ("too long", too_long)):
                with self.subTest(route=path, case=label), mock.patch(f"career.routes.{ai_function}") as ai:
                    res = self.post(path, text)
                    self.assertEqual(res.status_code, 400, res.text)
                    ai.assert_not_called()

    def test_the_messages_name_the_problem(self):
        res = self.post("/job-build-resume", "x" * (MAX_JOB_DESCRIPTION_CHARS + 1))
        self.assertIn(f"{MAX_JOB_DESCRIPTION_CHARS} max", res.json()["detail"])
        res = self.post("/job-build-resume", "x" * 10)
        self.assertIn("too short", res.json()["detail"])

    def test_text_exactly_at_the_limits_is_accepted_by_the_build_route(self):
        fake = {"resume_data": {"name": "N", "contact": "c", "summary": "", "skills": [], "experience": [], "education": []}}
        for size in (MIN_JOB_DESCRIPTION_CHARS, MAX_JOB_DESCRIPTION_CHARS):
            with self.subTest(size=size), mock.patch("career.routes.build_checked_resume", return_value=dict(fake)) as ai:
                res = self.post("/job-build-resume", "x" * size)
                self.assertEqual(res.status_code, 200, res.text)
                ai.assert_called_once()
                self.assertEqual(len(ai.call_args.args[1]), size)  # the checked, trimmed text is what is sent

    def test_a_huge_body_is_refused_by_the_request_model_before_the_handler(self):
        with mock.patch("career.routes.build_checked_resume") as ai:
            res = self.post("/job-build-resume", "x" * 500_000)
            self.assertEqual(res.status_code, 422, res.text)
            ai.assert_not_called()

    def test_whitespace_around_the_posting_is_not_counted(self):
        padded = "   " + "y" * MAX_JOB_DESCRIPTION_CHARS + "   "
        with mock.patch("career.routes.build_checked_resume", return_value={"resume_data": {"name": "N", "contact": "c", "summary": "", "skills": [], "experience": [], "education": []}}) as ai:
            self.assertEqual(self.post("/job-build-resume", padded).status_code, 200)
            ai.assert_called_once()
