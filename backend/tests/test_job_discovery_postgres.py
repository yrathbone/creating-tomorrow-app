"""Job discovery pilot on PostgreSQL (migration 0012): upgrade, downgrade, constraints and member isolation.

Runs ONLY when both are set:
  CT_JOBS_PG_TEST_URL      postgresql+psycopg://user:password@127.0.0.1:PORT/NAME_test   (local host, database name ends _test)
  CT_JOBS_PG_TEST_CONFIRM  disposable
The schema of that database is dropped and rebuilt by these tests. Never point this at a member or production database.
Without both settings every test is skipped and reports NOT RUN.
"""
import os
import subprocess
import sys
import unittest
from datetime import date
from unittest import mock
from urllib.parse import urlsplit

import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = os.environ.get("CT_JOBS_PG_TEST_URL", "")
CONFIRM = os.environ.get("CT_JOBS_PG_TEST_CONFIRM", "")


def _local_test_database(url: str) -> bool:
    if not url.startswith("postgresql+psycopg://"):
        return False
    parts = urlsplit(url)
    return parts.hostname in ("127.0.0.1", "localhost") and parts.path.rstrip("/").endswith("_test")


ENABLED = CONFIRM == "disposable" and _local_test_database(URL)
SKIP = "NOT RUN: set CT_JOBS_PG_TEST_URL to a local *_test database and CT_JOBS_PG_TEST_CONFIRM=disposable"


@unittest.skipUnless(ENABLED, SKIP)
class JobDiscoveryPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sa.create_engine(URL, pool_pre_ping=True)
        with cls.engine.begin() as conn:
            conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            conn.execute(sa.text("CREATE SCHEMA public"))
        cls._alembic("upgrade", "head")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    @classmethod
    def _alembic(cls, *args):
        env = dict(os.environ, DATABASE_URL=URL)
        return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, check=True)

    def _tables(self):
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(sa.text("select table_name from information_schema.tables where table_schema='public'"))}

    def test_upgrade_downgrade_reupgrade_on_postgresql(self):
        self.assertIn("job_postings", self._tables())
        self._alembic("downgrade", "0011")
        self.assertNotIn("job_postings", self._tables())
        self.assertNotIn("job_preferences", self._tables())
        self.assertIn("opportunities", self._tables())  # C-52 tables untouched by the downgrade
        self._alembic("upgrade", "head")
        self.assertIn("job_postings", self._tables())
        self.assertIn("job_preferences", self._tables())

    def _reset_rows(self):
        """Removes only rows these tests wrote (the disposable database is rebuilt in setUpClass)."""
        with self.engine.begin() as conn:
            conn.execute(sa.text("delete from job_preferences"))
            conn.execute(sa.text("delete from job_postings"))
            conn.execute(sa.text("delete from career_profiles"))
            conn.execute(sa.text("delete from users"))

    def _insert_posting(self, conn, **overrides):
        row = {"source": "greenhouse", "board_token": "sample-a", "source_job_id": "1", "title": "Program Manager",
               "company": "Sample Employer A", "location_text": "Chicago", "work_arrangement": "on_site",
               "employment_type": "full_time", "job_url": "https://jobs.example-employer.com/sample-a/1",
               "url_hash": "h1", "first_seen_on": date(2026, 11, 12), "last_seen_on": date(2026, 11, 12), "closed_on": None}
        row.update(overrides)
        conn.execute(sa.text(
            "insert into job_postings (source, board_token, source_job_id, title, company, location_text, work_arrangement, "
            "employment_type, job_url, url_hash, first_seen_on, last_seen_on, closed_on) values (:source, :board_token, "
            ":source_job_id, :title, :company, :location_text, :work_arrangement, :employment_type, :job_url, :url_hash, "
            ":first_seen_on, :last_seen_on, :closed_on)"), row)

    def _expect_rejected(self, **overrides):
        with self.assertRaises(sa.exc.IntegrityError):
            with self.engine.begin() as conn:
                self._insert_posting(conn, **overrides)

    def test_constraints_reject_bad_postings(self):
        self.addCleanup(self._reset_rows)
        with self.engine.begin() as conn:
            self._insert_posting(conn)
        self._expect_rejected(source_job_id="2", url_hash="h2", source="lever")                       # unsupported source
        self._expect_rejected(source_job_id="3", url_hash="h3", work_arrangement="telecommute")        # unknown arrangement
        self._expect_rejected(source_job_id="1", url_hash="h4")                                        # same board and job id
        self._expect_rejected(source_job_id="5", url_hash="h1")                                        # same apply link
        self._expect_rejected(source_job_id="6", url_hash="h6", first_seen_on=date(2026, 11, 13), last_seen_on=date(2026, 11, 12))

    def test_preferences_constraints_and_cascade(self):
        self.addCleanup(self._reset_rows)
        with self.engine.begin() as conn:
            uid = conn.execute(sa.text("insert into users (cognito_sub) values ('pg-synthetic-user') returning id")).scalar()
            pid = conn.execute(sa.text("insert into career_profiles (user_id) values (:u) returning id"), {"u": uid}).scalar()
            conn.execute(sa.text(
                "insert into job_preferences (career_profile_id, target_titles, locations, remote_ok, onsite_ok, employment_types, "
                "exclude_words, followed_boards) values (:p, '[]', '[]', true, true, '[]', '[]', '[]')"), {"p": pid})
        with self.assertRaises(sa.exc.IntegrityError):
            with self.engine.begin() as conn:  # a second preferences row for the same profile
                conn.execute(sa.text(
                    "insert into job_preferences (career_profile_id, target_titles, locations, remote_ok, onsite_ok, employment_types, "
                    "exclude_words, followed_boards) values (:p, '[]', '[]', true, true, '[]', '[]', '[]')"), {"p": pid})
        with self.assertRaises(sa.exc.IntegrityError):
            with self.engine.begin() as conn:  # negative pay
                conn.execute(sa.text(
                    "update job_preferences set min_base = -1 where career_profile_id = :p"), {"p": pid})
        with self.engine.begin() as conn:
            conn.execute(sa.text("delete from career_profiles where id = :p"), {"p": pid})
            left = conn.execute(sa.text("select count(*) from job_preferences where career_profile_id = :p"), {"p": pid}).scalar()
        self.assertEqual(left, 0)  # deleting a career profile removes its preferences

    def test_member_isolation_through_the_routes(self):
        self._reset_rows()
        self.addCleanup(self._reset_rows)
        from auth.dependencies import get_current_user
        from career import discovery_routes
        from career.routes import router as career_router
        from db import get_db_session
        from models import CareerProfile, JobPosting, User

        SessionLocal = sessionmaker(bind=self.engine)
        with SessionLocal() as db:
            a = User(cognito_sub="pg-member-a")
            b = User(cognito_sub="pg-member-b")
            db.add_all([a, b])
            db.commit()
            pa, pb = CareerProfile(user_id=a.id), CareerProfile(user_id=b.id)
            db.add_all([pa, pb])
            db.commit()
            db.add(JobPosting(source="greenhouse", board_token="sample-a", source_job_id="iso-1", title="Program Manager",
                              company="Sample Employer A", location_text="Chicago", work_arrangement="on_site",
                              employment_type="full_time", job_url="https://jobs.example-employer.com/sample-a/iso-1",
                              url_hash="iso-hash-1", first_seen_on=date(2026, 11, 12), last_seen_on=date(2026, 11, 12)))
            db.commit()
            ids = {"a": a.id, "b": b.id}

        boards = [{"source": "greenhouse", "board_token": "sample-a", "name": "Sample Employer A"}]
        env = {"CT_JOB_DISCOVERY_ENABLED": "1", "CT_JOB_DISCOVERY_ALLOWED_SUBS": "pg-member-a,pg-member-b", "CT_JOB_BOARD_FOLLOW_LIMIT": "10"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(discovery_routes, "load_registry", return_value=boards):
            app = FastAPI()
            app.include_router(career_router, prefix="/api/career")
            app.include_router(discovery_routes.router, prefix="/api/career")
            current = {"id": ids["a"]}

            def session():
                s = SessionLocal()
                try:
                    yield s
                finally:
                    s.close()

            def user():
                with SessionLocal() as s:
                    return s.get(User, current["id"])

            app.dependency_overrides[get_db_session] = session
            app.dependency_overrides[get_current_user] = user
            client = TestClient(app, raise_server_exceptions=False)

            put = client.put("/api/career/job-preferences", json={"target_titles": ["Program Manager"], "locations": ["Chicago"],
                                                                  "followed_boards": ["greenhouse:sample-a"]})
            self.assertEqual(put.status_code, 200, put.text)
            self.assertEqual(len(client.get("/api/career/job-matches").json()["matches"]), 1)

            current["id"] = ids["b"]
            self.assertEqual(client.get("/api/career/job-preferences").json()["target_titles"], [])
            self.assertEqual(client.get("/api/career/job-matches").json()["matches"], [])


if __name__ == "__main__":
    unittest.main()
