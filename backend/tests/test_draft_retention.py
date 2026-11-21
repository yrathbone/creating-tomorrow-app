"""Interview-draft retention: a draft is deleted after 30 days without an update (career/draft_retention.py).

Runs against a DISPOSABLE PostgreSQL database only. Set DISPOSABLE_TEST_DATABASE_URL to a database whose name starts with
ct_draft_disposable and whose host is localhost or 127.0.0.1. Otherwise the tests are skipped. They never use DATABASE_URL
and never touch the C-52 test database. They log counts only; no draft content is printed.

Run from backend/:
  DISPOSABLE_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55544/ct_draft_disposable python -m unittest tests.test_draft_retention -v
"""
import contextlib
import io
import os
import unittest
from unittest import mock
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import career.draft_sweep as draft_sweep
from career.draft_retention import sweep_stale_drafts
from db import Base, get_db_session
from models import Application, CareerProfile, ResumeIngestionDraft, ResumeVersion, ScanHistory, Skill, User
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B

URL_ENV = "DISPOSABLE_TEST_DATABASE_URL"
OTHER_TABLES = (User, CareerProfile, Application, ResumeVersion, ScanHistory, Skill)


def _disposable_url() -> str:
    raw = os.environ[URL_ENV]
    parts = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    name = (parts.path or "/").lstrip("/")
    if parts.hostname not in ("localhost", "127.0.0.1") or not name.startswith("ct_draft_disposable"):
        raise RuntimeError("refusing to run: the URL must be a ct_draft_disposable* database on localhost")
    return raw


@unittest.skipUnless(os.environ.get(URL_ENV), f"set {URL_ENV} to a disposable local PostgreSQL database to run")
class DraftRetention(OwnershipTestCase):
    def setUp(self):
        super().setUp()  # the in-memory app harness (real tokens); its database is replaced below
        engine = create_engine(_disposable_url(), pool_pre_ping=True)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.addCleanup(self._drop, engine)
        self.Session = sessionmaker(bind=engine)

        def session():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        self.client.app.dependency_overrides[get_db_session] = session

    @staticmethod
    def _drop(engine):
        Base.metadata.drop_all(engine)
        engine.dispose()

    # -- helpers -------------------------------------------------------
    def add_draft(self, sub, summary="interview answers: private"):
        with self.Session() as s:
            s.add(ResumeIngestionDraft(career_profile_id=self.profile_id_for(sub), analysis_summary=summary))
            s.commit()

    def age_draft(self, sub, days):
        with self.Session() as s:
            s.execute(
                text("UPDATE resume_ingestion_drafts SET updated_at = now() - make_interval(days => :d) WHERE career_profile_id = :p"),
                {"d": days, "p": self.profile_id_for(sub)},
            )
            s.commit()

    def draft_updated_at(self, sub):
        with self.Session() as s:
            row = s.query(ResumeIngestionDraft).filter_by(career_profile_id=self.profile_id_for(sub)).one_or_none()
            return row.updated_at if row else None

    def draft_count(self):
        with self.Session() as s:
            return s.query(ResumeIngestionDraft).count()

    def other_table_counts(self):
        with self.Session() as s:
            return {m.__tablename__: s.query(m).count() for m in OTHER_TABLES}

    # -- the rule ------------------------------------------------------
    def test_a_draft_31_days_old_is_gone_when_read(self):
        self.build_world()
        self.add_draft(SUB_A)
        self.age_draft(SUB_A, 31)
        res = self.call("GET", "/resume-draft", self.a)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json())
        self.assertIsNone(self.draft_updated_at(SUB_A))

    def test_a_draft_29_days_old_is_kept_and_viewing_it_does_not_reset_the_clock(self):
        self.build_world()
        self.add_draft(SUB_A)
        self.age_draft(SUB_A, 29)
        before = self.draft_updated_at(SUB_A)
        res = self.call("GET", "/resume-draft", self.a)
        self.assertIsNotNone(res.json())
        self.assertEqual(self.draft_updated_at(SUB_A), before, "viewing must not change updated_at")
        self.assertEqual(self.draft_count(), 1)

    def test_sweep_deletes_only_the_stale_draft_and_no_other_table_changes(self):
        self.build_world()
        self.add_draft(SUB_A, "stale answers")
        self.add_draft(SUB_B, "fresh answers")
        self.age_draft(SUB_A, 31)
        self.age_draft(SUB_B, 29)
        counts_before = self.other_table_counts()
        with self.Session() as s:
            deleted = sweep_stale_drafts(s)
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.draft_updated_at(SUB_A))
        self.assertIsNotNone(self.draft_updated_at(SUB_B))
        self.assertEqual(self.other_table_counts(), counts_before, "saved resumes, scans, applications, profiles are unchanged")

    def test_the_daily_sweep_prints_a_count_only(self):
        self.build_world()
        self.add_draft(SUB_A, "stale answers that must never be printed")
        self.age_draft(SUB_A, 31)
        out = io.StringIO()
        with mock.patch.object(draft_sweep, "get_session", return_value=self.Session()), contextlib.redirect_stdout(out):
            code = draft_sweep.main()
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "interview drafts deleted: 1\n")
        self.assertNotIn("stale answers", out.getvalue())

    def test_account_deletion_still_removes_drafts(self):
        self.build_world()
        self.add_draft(SUB_A)
        self.add_draft(SUB_B)
        self.age_draft(SUB_A, 3)
        res = self.call("POST", "/account/delete", self.a, json={"confirm": "DELETE"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.draft_count(), 1, "A's drafts are gone with the account; only B's draft remains")
        self.assertIsNotNone(self.draft_updated_at(SUB_B))


if __name__ == "__main__":
    unittest.main()
