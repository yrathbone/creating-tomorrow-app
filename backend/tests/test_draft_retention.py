"""Interview-draft retention (Jo direction, 2026-11-22): a resume-interview draft expires 30 days after its last change.

Run from the backend folder:  python -m unittest tests.test_draft_retention -v
Fresh in-memory SQLite database per test (OwnershipTestCase). No AI call: the AI function is mocked where a route needs it.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

from career.draft_retention import DRAFT_GONE_MESSAGE, DRAFT_RETENTION, live_draft, sweep_stale_drafts
from models import Experience, ResumeIngestionDraft
from tests.test_ownership import SUB_A, SUB_B, OwnershipTestCase

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


class DraftRetention(OwnershipTestCase):
    def put_draft(self, sub, updated_at):
        pid = self.profile_id_for(sub)
        with self.Session() as s:
            s.add(ResumeIngestionDraft(career_profile_id=pid, roles=[{"title": "Teacher"}], history=[], updated_at=updated_at))
            s.commit()

    def draft_rows(self):
        with self.Session() as s:
            return s.query(ResumeIngestionDraft).count()

    def get_draft(self, who):
        return self.call("GET", "/resume-draft", who)

    def test_the_retention_period_is_thirty_days(self):
        self.assertEqual(DRAFT_RETENTION, timedelta(days=30))

    def test_a_recent_draft_is_returned(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=1))
        res = self.get_draft(self.a)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNotNone(res.json())
        self.assertEqual(self.draft_rows(), 1)

    def test_an_expired_draft_is_not_returned_by_the_route(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=31))
        res = self.get_draft(self.a)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json())
        self.assertEqual(self.draft_rows(), 0)

    def test_a_draft_last_changed_thirty_one_days_ago_is_gone_and_deleted(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, NOW - timedelta(days=31))
        with self.Session() as s:
            self.assertIsNone(live_draft(s, self.profile_id_for(SUB_A), now=NOW))
        self.assertEqual(self.draft_rows(), 0, "the expired row is deleted, not just hidden")

    def test_twenty_nine_days_is_still_kept(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, NOW - timedelta(days=29, hours=23))
        with self.Session() as s:
            self.assertIsNotNone(live_draft(s, self.profile_id_for(SUB_A), now=NOW))
        self.assertEqual(self.draft_rows(), 1)

    def test_exactly_thirty_days_is_expired(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, NOW - DRAFT_RETENTION)
        with self.Session() as s:
            self.assertIsNone(live_draft(s, self.profile_id_for(SUB_A), now=NOW))

    def test_reading_the_draft_does_not_extend_its_life(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, NOW - timedelta(days=31))
        with self.Session() as s:
            row = s.query(ResumeIngestionDraft).one()
            self.assertIsNone(live_draft(s, row.career_profile_id, now=NOW))
        self.assertEqual(self.draft_rows(), 0)

    def test_manual_discard_still_works_before_expiry(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, NOW - timedelta(days=2))
        res = self.call("DELETE", "/resume-draft", self.a)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"discarded": True})
        self.assertEqual(self.draft_rows(), 0)

    def test_one_members_expiry_never_touches_another_members_draft(self):
        self.onboard(self.a)
        self.onboard(self.b)
        self.put_draft(SUB_A, NOW - timedelta(days=40))
        self.put_draft(SUB_B, NOW - timedelta(days=1))
        with self.Session() as s:
            self.assertIsNone(live_draft(s, self.profile_id_for(SUB_A), now=NOW))
            self.assertIsNotNone(live_draft(s, self.profile_id_for(SUB_B), now=NOW))
        self.assertEqual(self.draft_rows(), 1)

    def test_sweep_removes_only_the_expired_drafts(self):
        self.onboard(self.a)
        self.onboard(self.b)
        self.put_draft(SUB_A, NOW - timedelta(days=45))
        self.put_draft(SUB_B, NOW - timedelta(days=3))
        with self.Session() as s:
            self.assertEqual(sweep_stale_drafts(s, now=NOW), 1)
        self.assertEqual(self.draft_rows(), 1)
        with self.Session() as s:
            self.assertEqual(sweep_stale_drafts(s, now=NOW), 0, "a second sweep changes nothing")

    def test_resume_discover_refuses_an_expired_draft_before_any_ai_call(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=31))
        with mock.patch("career.routes.discover", return_value={"stage": "questions", "questions": []}) as ai:
            res = self.call("POST", "/resume-discover", self.a, json={"resume_data": {"roles": []}, "history": [{"id": "old", "answer": "stale"}]})
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(res.json()["detail"], DRAFT_GONE_MESSAGE)
        ai.assert_not_called()
        self.assertEqual(self.draft_rows(), 0)

    def test_resume_discover_refuses_a_discarded_draft_before_any_ai_call(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=1))
        self.assertEqual(self.call("DELETE", "/resume-draft", self.a).status_code, 200)
        with mock.patch("career.routes.discover", return_value={"stage": "questions", "questions": []}) as ai:
            res = self.call("POST", "/resume-discover", self.a, json={"resume_data": {"roles": []}, "history": [{"id": "x", "answer": "after discard"}]})
        self.assertEqual(res.status_code, 409, res.text)
        ai.assert_not_called()

    def test_resume_discover_with_a_live_draft_still_calls_the_ai_and_advances_the_round(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=1))
        history = [{"id": "q1", "answer": "I ran a store"}]
        with mock.patch("career.routes.discover", return_value={"stage": "questions", "questions": [{"id": "q2"}]}) as ai:
            res = self.call("POST", "/resume-discover", self.a, json={"resume_data": {"roles": []}, "history": history, "round_number": 1})
        self.assertEqual(res.status_code, 200, res.text)
        ai.assert_called_once()
        with self.Session() as s:
            row = s.query(ResumeIngestionDraft).one()
            self.assertEqual(row.history, [], "raw answers are not kept after analysis (2026-11-22 direction)")
            self.assertEqual(row.round_number, 2)

    def test_resume_save_refuses_an_expired_draft_and_saves_nothing(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=31))
        role = {"title": "Store Manager", "organization": "Corner Shop", "bullets": ["Ran the store"]}
        res = self.call("POST", "/resume-save", self.a, json={"roles": [role]})
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(res.json()["detail"], DRAFT_GONE_MESSAGE)
        with self.Session() as s:
            self.assertEqual(s.query(Experience).filter_by(career_profile_id=self.profile_id_for(SUB_A)).count(), 0)

    def test_resume_save_refuses_a_discarded_draft(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=1))
        self.call("DELETE", "/resume-draft", self.a)
        res = self.call("POST", "/resume-save", self.a, json={"roles": [{"title": "Teacher", "organization": "School", "bullets": []}]})
        self.assertEqual(res.status_code, 409, res.text)

    def test_resume_save_with_a_live_draft_saves_and_then_clears_the_draft(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=1))
        res = self.call("POST", "/resume-save", self.a, json={"roles": [{"title": "Teacher", "organization": "School", "bullets": ["Taught"]}]})
        self.assertEqual(res.status_code, 200, res.text)
        with self.Session() as s:
            self.assertEqual(s.query(Experience).filter_by(career_profile_id=self.profile_id_for(SUB_A)).count(), 1)
        self.assertEqual(self.draft_rows(), 0, "the saved draft is cleared, as before")

if __name__ == "__main__":
    import unittest
    unittest.main()
