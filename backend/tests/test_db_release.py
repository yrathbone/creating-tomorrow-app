"""A slow AI call must not hold a database connection (risk-audit finding F-04)."""
import os
import re
import tempfile
import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from db import Base, get_db_session, release_db_connection
from models import ScanHistory
from tests.test_ownership import SUB_A, OwnershipTestCase

ROUTES = os.path.join(os.path.dirname(__file__), "..", "career", "routes.py")


class ReleaseHelperTests(unittest.TestCase):
    def setUp(self):
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        self.engine = create_engine(f"sqlite:///{path}", poolclass=QueuePool, pool_size=2, max_overflow=0, pool_timeout=0.5)
        with self.engine.begin() as c:
            c.execute(text("create table t(x int)"))
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_a_session_that_ran_a_query_holds_its_connection_until_released(self):
        s = self.Session()
        s.execute(text("select 1"))
        self.assertEqual(self.engine.pool.checkedout(), 1, "the problem this fixes")
        release_db_connection(s)
        self.assertEqual(self.engine.pool.checkedout(), 0)
        s.close()

    def test_the_session_still_works_afterwards(self):
        s = self.Session()
        s.execute(text("select 1"))
        release_db_connection(s)
        self.assertEqual(s.execute(text("select 41 + 1")).scalar(), 42)
        s.close()

    def test_five_long_requests_no_longer_use_up_the_pool(self):
        sessions = []
        for _ in range(5):                      # five "requests", each runs one query, then a long AI call
            s = self.Session()
            s.execute(text("select 1"))
            release_db_connection(s)
            sessions.append(s)
        self.assertEqual(self.engine.pool.checkedout(), 0)
        extra = self.Session()
        self.assertEqual(extra.execute(text("select 1")).scalar(), 1, "a sixth request still gets a connection")
        extra.close()
        for s in sessions:
            s.close()

    def test_unsaved_changes_are_never_thrown_away(self):
        from sqlalchemy import Column, Integer
        from sqlalchemy.orm import declarative_base
        B = declarative_base()

        class Row(B):
            __tablename__ = "rows"
            id = Column(Integer, primary_key=True)

        B.metadata.create_all(self.engine)
        s = self.Session()
        s.add(Row(id=1))
        release_db_connection(s)              # pending change: left alone
        s.commit()
        self.assertEqual(self.Session().query(Row).count(), 1)
        s.close()


class RouteTests(OwnershipTestCase):
    def test_the_ai_call_runs_with_no_open_database_transaction_and_the_route_still_finishes(self):
        self.onboard(self.a)
        sessions, seen = [], {}

        def recording_session():
            s = self.Session()
            sessions.append(s)
            try:
                yield s
            finally:
                s.close()

        self.client.app.dependency_overrides[get_db_session] = recording_session

        def fake_scan(profile_text):
            seen["in_transaction_during_ai_call"] = sessions[-1].in_transaction()
            return {"analysis_summary": "Nothing new stood out.", "categories": [], "questions": []}

        with mock.patch("career.routes.start_skill_scan", fake_scan):
            res = self.call("POST", "/skill-scan", self.a)
        self.assertEqual(res.status_code, 200)
        self.assertIs(seen["in_transaction_during_ai_call"], False)
        self.assertIsNotNone(res.json()["scan_history_id"], "work after the AI call (saving the result) still happens")
        with self.Session() as s:
            self.assertEqual(s.query(ScanHistory).filter_by(scan_type="skill_scan").count(), 1)


class EveryAiRouteTests(unittest.TestCase):
    def test_every_ai_call_in_the_signed_in_routes_is_preceded_by_a_release_and_the_route_has_a_db_session(self):
        with open(ROUTES, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        checked = 0
        for i, line in enumerate(lines):
            if "await run_in_threadpool(" in line and "extract_text" not in line:
                j = i
                while not lines[j].strip().startswith("try:"):
                    j -= 1
                self.assertIn("release_db_connection(db)", lines[j - 1], f"line {i + 1}: release before the AI call")
                k = j
                while not lines[k].startswith("async def "):
                    k -= 1
                signature = "\n".join(lines[k:j])
                self.assertRegex(signature, r"db: Session = Depends\(get_db_session\)", f"{lines[k]} needs the session")
                checked += 1
        self.assertEqual(checked, 9)


if __name__ == "__main__":
    unittest.main()
