"""Job-flow gap-interview answers are removed after a successful tailored-resume build (Jo, 2026-11-22).

What these tests prove (mocked AI, local SQLite): after a successful build the raw qa_history key is gone from the
scan; other scan metadata is kept; a failed build keeps the answers so a retry is possible; a later successful build
removes them; another member cannot build against or clear this member's scan.

What they do NOT prove: PostgreSQL behaviour, provider-side retention, or what the browser keeps.

Run from the backend folder:  python -m unittest tests.test_job_build_qa_disposal -v
"""
import os
from unittest import mock

import abuse_guard
from career.job_match import JobMatchError
from models import ResumeVersion, ScanHistory
from tests.test_ownership import JOB_TEXT, SUB_A, SUB_B, OwnershipTestCase

ANSWER = "I supervised four cashiers and wrote the weekly rota myself"
OTHER_KEY = {"terms": [{"term": "rota", "status": "backed"}], "fingerprint": "abc"}
BUILT = {"resume_data": {"name": "N", "contact": "c", "summary": "", "skills": [], "experience": [], "education": []}}


class JobBuildQaDisposal(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        # Fresh rate limiter per test, so these tests do not use up the shared limit other test modules rely on.
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()

    def make_scan(self, sub, qa=True):
        pid = self.profile_id_for(sub)
        result = {"term_plan": OTHER_KEY, "match": {"score": 72}}
        if qa:
            result["qa_history"] = [{"id": "q1", "answer": ANSWER}]
        with self.Session() as s:
            scan = ScanHistory(career_profile_id=pid, scan_type="job_comparison", job_title="Rota lead", summary_text="s", result_data=result)
            s.add(scan)
            s.commit()
            return scan.id

    def scan_row(self, scan_id):
        with self.Session() as s:
            return dict(s.get(ScanHistory, scan_id).result_data or {})

    def versions(self, sub):
        with self.Session() as s:
            return s.query(ResumeVersion).filter_by(career_profile_id=self.profile_id_for(sub)).count()

    def build(self, who, scan_id, qa, mocked=None):
        body = {"job_description": JOB_TEXT, "name": "N", "contact": "c@example.com", "scan_history_id": scan_id, "qa_history": qa}
        with mock.patch("career.routes.build_checked_resume", side_effect=mocked) as ai:
            if mocked is None:
                ai.return_value = BUILT
            res = self.call("POST", "/job-build-resume", who, json=body)
        return res, ai

    def test_a_successful_build_removes_the_raw_answers_and_keeps_everything_else(self):
        self.onboard(self.a)
        scan_id = self.make_scan(SUB_A, qa=False)
        res, _ = self.build(self.a, scan_id, [{"id": "q1", "answer": ANSWER}])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.versions(SUB_A), 1, "the tailored resume is saved")
        data = self.scan_row(scan_id)
        self.assertNotIn("qa_history", data, "the raw answers are removed after a successful build")
        self.assertEqual(data["term_plan"], OTHER_KEY, "the term plan is kept")
        self.assertEqual(data["match"], {"score": 72}, "the match details are kept")
        self.assertNotIn(ANSWER, res.text, "the response does not carry the raw answers")

    def test_a_failed_build_keeps_the_answers_for_a_retry(self):
        self.onboard(self.a)
        scan_id = self.make_scan(SUB_A, qa=False)
        res, _ = self.build(self.a, scan_id, [{"id": "q1", "answer": ANSWER}], mocked=JobMatchError("provider down"))
        self.assertNotEqual(res.status_code, 200, res.text)
        self.assertEqual(self.versions(SUB_A), 0, "no resume is saved")
        self.assertEqual(self.scan_row(scan_id)["qa_history"], [{"id": "q1", "answer": ANSWER}], "answers kept for retry")
        self.assertNotIn(ANSWER, res.text, "the error does not echo the answer")

    def test_a_later_successful_build_after_a_failure_removes_the_answers(self):
        self.onboard(self.a)
        scan_id = self.make_scan(SUB_A, qa=False)
        self.build(self.a, scan_id, [{"id": "q1", "answer": ANSWER}], mocked=JobMatchError("down"))
        self.assertIn("qa_history", self.scan_row(scan_id))
        res, _ = self.build(self.a, scan_id, [{"id": "q1", "answer": ANSWER}])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertNotIn("qa_history", self.scan_row(scan_id))
        self.assertEqual(self.scan_row(scan_id)["term_plan"], OTHER_KEY)

    def test_a_build_with_no_scan_saves_the_resume_and_touches_no_scan(self):
        self.onboard(self.a)
        res, _ = self.build(self.a, None, [{"id": "q1", "answer": ANSWER}])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.versions(SUB_A), 1)

    def test_another_member_cannot_build_against_or_clear_this_members_answers(self):
        self.onboard(self.a)
        self.onboard(self.b)
        scan_a = self.make_scan(SUB_A, qa=True)
        res, ai = self.build(self.b, scan_a, [{"id": "q1", "answer": "B's own words"}])
        self.assertEqual(res.status_code, 400, res.text)
        ai.assert_not_called()
        self.assertEqual(self.scan_row(scan_a)["qa_history"], [{"id": "q1", "answer": ANSWER}], "A's answers are untouched")
        self.assertEqual(self.versions(SUB_B), 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
