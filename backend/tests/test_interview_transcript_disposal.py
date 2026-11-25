"""Raw interview answers are not kept on the server after the AI analyses them (2026-11-22 direction).

What these tests prove: the server's saved interview draft holds no raw answer history after a successful analysis;
structured suggestions stay for review; a failed analysis changes nothing; nothing reaches the Career Profile until
the member saves; a typed answer goes through the same path.

What they do NOT prove: the browser's memory is cleared (see the frontend test), the AI provider's retention, or
PostgreSQL behaviour. The AI call is mocked. No database server is used.

Run from the backend folder:  python -m unittest tests.test_interview_transcript_disposal -v
"""
from datetime import datetime, timezone
from unittest import mock

from elevate import ElevateError
from models import Experience, ResumeIngestionDraft, Skill
from tests.test_ownership import SUB_A, OwnershipTestCase

RAW_ANSWER = "I ran the whole Saturday shift alone and opened the register for the first time"
SUGGESTION = {"category": "Customer service", "bullet_text": "Opened the register and ran a solo shift", "source_round": 1}


class TranscriptDisposal(OwnershipTestCase):
    def put_draft(self, history=None, facts=None):
        pid = self.profile_id_for(SUB_A)
        with self.Session() as s:
            s.add(ResumeIngestionDraft(
                career_profile_id=pid, roles=[{"title": "Cashier"}], history=history or [],
                discovered_facts=facts or [], updated_at=datetime.now(timezone.utc),
            ))
            s.commit()

    def draft(self):
        with self.Session() as s:
            row = s.query(ResumeIngestionDraft).one()
            return {"history": list(row.history or []), "facts": list(row.discovered_facts or []), "round": row.round_number}

    def count(self, model):
        with self.Session() as s:
            return s.query(model).filter_by(career_profile_id=self.profile_id_for(SUB_A)).count()

    def discover(self, history, result):
        with mock.patch("career.routes.discover", return_value=result) as ai:
            res = self.call("POST", "/resume-discover", self.a, json={
                "resume_data": {"roles": [{"title": "Cashier"}]}, "categories": ["Customer service"],
                "history": history, "round_number": 1,
            })
        return res, ai

    def test_after_a_successful_analysis_the_draft_holds_no_raw_answer_history(self):
        self.onboard(self.a)
        self.put_draft()
        history = [{"id": "q1", "category": "Customer service", "question": "What did you do?", "type": "detail", "answer": RAW_ANSWER}]
        res, ai = self.discover(history, {"stage": "questions", "questions": [{"id": "q2", "question": "Which shift?", "type": "detail"}]})
        self.assertEqual(res.status_code, 200, res.text)
        ai.assert_called_once()  # the AI did receive the answer for analysis
        self.assertEqual(self.draft()["history"], [], "the raw answer must not be saved")

    def test_structured_suggestions_stay_for_review_when_the_analysis_reaches_confirm(self):
        self.onboard(self.a)
        self.put_draft()
        history = [{"id": "q1", "answer": RAW_ANSWER}]
        res, _ = self.discover(history, {"stage": "confirm", "discovered_facts": [SUGGESTION]})
        self.assertEqual(res.status_code, 200, res.text)
        saved = self.draft()
        self.assertEqual(saved["history"], [])
        self.assertEqual(saved["facts"], [SUGGESTION], "the structured suggestion is kept for the member to review")

    def test_the_suggestions_are_not_in_the_profile_until_the_member_saves(self):
        self.onboard(self.a)
        self.put_draft()
        res, _ = self.discover([{"id": "q1", "answer": RAW_ANSWER}], {"stage": "confirm", "discovered_facts": [SUGGESTION]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.count(Experience), 0)
        self.assertEqual(self.count(Skill), 0)

    def test_a_failed_analysis_changes_nothing_and_keeps_the_previous_draft(self):
        self.onboard(self.a)
        self.put_draft(history=[{"id": "q0", "answer": "earlier, already analysed"}], facts=[])
        before = self.draft()
        with mock.patch("career.routes.discover", side_effect=ElevateError("provider down")) as ai:
            res = self.call("POST", "/resume-discover", self.a, json={
                "resume_data": {"roles": []}, "categories": [], "history": [{"id": "q1", "answer": RAW_ANSWER}], "round_number": 1,
            })
        ai.assert_called_once()
        self.assertNotEqual(res.status_code, 200)
        self.assertNotIn(RAW_ANSWER, res.text, "the error does not echo the answer")
        self.assertEqual(self.draft(), before, "a failed call must not write the new answer anywhere")

    def test_a_typed_answer_goes_through_the_same_path(self):
        self.onboard(self.a)
        self.put_draft()
        res, ai = self.discover([{"id": "q1", "answer": "Typed, not spoken"}], {"stage": "questions", "questions": []})
        self.assertEqual(res.status_code, 200, res.text)
        ai.assert_called_once()
        self.assertEqual(self.draft()["history"], [])

    def test_saving_is_the_only_step_that_writes_profile_rows_and_it_clears_the_draft(self):
        self.onboard(self.a)
        self.put_draft(facts=[SUGGESTION])
        self.assertEqual(self.count(Experience), 0)
        res = self.call("POST", "/resume-save", self.a, json={
            "roles": [{"title": "Cashier", "organization": "Corner Shop", "bullets": ["Opened the register"]}],
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.count(Experience), 1)
        with self.Session() as s:
            self.assertEqual(s.query(ResumeIngestionDraft).count(), 0, "the draft (and any remaining suggestions) is cleared on save")


if __name__ == "__main__":
    import unittest
    unittest.main()
