"""The daily draft sweep job (FOR REVIEW ONLY, 2026-11-22): it deletes expired interview drafts and prints a count only.

Run from the backend folder:  python -m unittest tests.test_draft_sweep -v
Uses the in-memory SQLite test database. Nothing is scheduled or deployed by these tests.
"""
import contextlib
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from career import draft_sweep
from models import ResumeIngestionDraft
from tests.test_ownership import SUB_A, SUB_B, OwnershipTestCase

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


class DraftSweepJob(OwnershipTestCase):
    def put_draft(self, sub, updated_at):
        pid = self.profile_id_for(sub)
        with self.Session() as s:
            s.add(ResumeIngestionDraft(career_profile_id=pid, roles=[], history=[], updated_at=updated_at))
            s.commit()

    def draft_rows(self):
        with self.Session() as s:
            return s.query(ResumeIngestionDraft).count()

    def test_the_job_deletes_only_expired_drafts_and_prints_a_count(self):
        self.onboard(self.a)
        self.onboard(self.b)
        now = datetime.now(timezone.utc)
        self.put_draft(SUB_A, now - timedelta(days=40))
        self.put_draft(SUB_B, now - timedelta(days=2))
        out = io.StringIO()
        with mock.patch.object(draft_sweep, "get_session", lambda: self.Session()), contextlib.redirect_stdout(out):
            code = draft_sweep.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "interview drafts deleted: 1")
        self.assertEqual(self.draft_rows(), 1)

    def test_the_job_prints_no_draft_content(self):
        self.onboard(self.a)
        self.put_draft(SUB_A, datetime.now(timezone.utc) - timedelta(days=40))
        out = io.StringIO()
        with mock.patch.object(draft_sweep, "get_session", lambda: self.Session()), contextlib.redirect_stdout(out):
            draft_sweep.main()
        self.assertNotIn("roles", out.getvalue())
        self.assertNotIn("history", out.getvalue())

    def test_the_render_cron_is_declared_for_review_and_not_auto_deployed(self):
        with open(os.path.join(ROOT, "render.yaml"), encoding="utf-8") as f:
            text = f.read()
        block = text[text.index("name: creating-tomorrow-draft-sweep"):]
        self.assertIn("type: cron", text[text.rindex("- type: cron", 0, text.index("name: creating-tomorrow-draft-sweep")):text.index("name: creating-tomorrow-draft-sweep")])
        self.assertIn('schedule: "17 3 * * *"', block)
        self.assertIn('startCommand: "cd backend && python -m career.draft_sweep"', block)
        self.assertIn('autoDeployTrigger: "off"', block)
        self.assertIn("DATABASE_URL", block)
        self.assertNotIn("postgres://", block)
        self.assertNotIn("postgresql://", block)


class NullTimestampIsExpired(unittest.TestCase):
    """A draft with no recorded last change is treated as expired (defensive). The database column is NOT NULL, so this
    cannot happen in a stored row; the test covers the code path the sweep relies on."""

    def test_a_draft_with_no_updated_at_is_treated_as_expired(self):
        from career.draft_retention import _expired
        now = datetime.now(timezone.utc)
        no_timestamp = type("Row", (), {"updated_at": None})()
        self.assertTrue(_expired(no_timestamp, now))

    def test_a_recent_draft_is_not_expired_by_the_same_rule(self):
        from career.draft_retention import _expired
        now = datetime.now(timezone.utc)
        recent = type("Row", (), {"updated_at": now - timedelta(days=1)})()
        self.assertFalse(_expired(recent, now))

if __name__ == "__main__":
    unittest.main()
