"""C-52 PostgreSQL two-session validation of the Step B two-phase approval (prepare without a lock, commit under row locks).

Each scenario runs two real requests on two real database sessions (two threads, two connections). The first request is paused at a
named point with a test-only wrapper (unittest.mock; nothing is registered in production code). The second request runs to completion
on PostgreSQL in the middle of the first. Locks are real here; SQLite-based tests cannot show this.

Runs ONLY against the configured disposable C-52 test database (tests/harness/pg_test_config.py). Synthetic members only. A private schema
is created for the run and dropped at the end. Nothing is printed except results.
"""
import hashlib
import os
import sys
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "tests", "harness"))
sys.path.insert(0, BACKEND)
import pg_test_config  # noqa: E402

try:
    CFG = pg_test_config.load()
    URL, EXPECTED_DB = CFG["url"], CFG["database"]
    VERIFIED = pg_test_config.verify(CFG)
    SKIP_REASON = ""
except pg_test_config.ConfigError as e:
    CFG, URL, EXPECTED_DB, VERIFIED = None, "", "", None
    SKIP_REASON = str(e)

if VERIFIED is not None:
    import sqlalchemy as sa
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import auth.dependencies as deps
    from career import opportunities as opp
    from career import review_gate as rg
    from career.opportunities import router as opportunities_router
    from career.routes import router as career_router
    from db import Base, get_db_session
    from models import CareerProfile, Experience, ResumeVersion, User
    from tests.test_signed_in_harness import REGION, POOL, CLIENT, _jwk, _new_key, access_token

GATE = "CT_GENERAL_RESUME_TRUTH_GATE"


def _paused(target, name, nth, action):
    """Test-only interleaving. The nth call of target.name made inside the with-block runs action() first, then the real call
    continues. The request that is paused is the one in flight; action() starts the second request (on its own thread and session)
    and waits for it. Nothing is registered in production code. Scoped to the with-block."""
    real = getattr(target, name)
    state = {"calls": 0, "fired": False}
    lock = threading.Lock()

    def wrapper(*args, **kwargs):
        with lock:
            state["calls"] += 1
            run = state["calls"] == nth and not state["fired"]
            if run:
                state["fired"] = True
        if run:
            action()
        return real(*args, **kwargs)
    return mock.patch.object(target, name, side_effect=wrapper)


@unittest.skipUnless(VERIFIED is not None, "NOT RUN: " + SKIP_REASON)
class PostgresTwoPhaseApproval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "c52_twophase_" + uuid.uuid4().hex[:10]
        url = URL.replace("postgresql://", "postgresql+psycopg://", 1)
        admin = sa.create_engine(url)
        with admin.begin() as c:
            c.execute(sa.text(f'create schema "{cls.schema}"'))
        admin.dispose()
        cls.engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={cls.schema}"}, pool_size=12, max_overflow=4)
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)
        cls.key = _new_key()
        cls.a_sub, cls.b_sub = "pg-twophase-a-" + uuid.uuid4().hex[:6], "pg-twophase-b-" + uuid.uuid4().hex[:6]
        cls._patches = [
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_jwks_cache", {"keys": [_jwk(cls.key)]}),
            mock.patch.object(deps, "_jwks_fetched_at", None),
            mock.patch.object(deps, "_jwks_last_attempt", time.monotonic()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": f"{cls.a_sub},{cls.b_sub}"}),
        ]
        for p in cls._patches:
            p.start()
        app = FastAPI()
        app.include_router(career_router, prefix="/api/career")
        app.include_router(opportunities_router, prefix="/api/career")

        def session():
            s = cls.Session()
            try:
                yield s
            finally:
                s.close()
        app.dependency_overrides[get_db_session] = session
        cls.app = app
        cls.a = {"Authorization": "Bearer " + access_token(cls.key, cls.a_sub)}
        cls.b = {"Authorization": "Bearer " + access_token(cls.key, cls.b_sub)}
        cls.a_profile, cls.a_experience = cls._seed(cls.a_sub, "Synthetic A")
        cls._seed(cls.b_sub, "Synthetic B")

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        with cls.engine.begin() as c:
            c.execute(sa.text(f'drop schema "{cls.schema}" cascade'))
        cls.engine.dispose()

    @classmethod
    def _seed(cls, sub, name):
        db = cls.Session()
        u = User(cognito_sub=sub, consent_given_at=datetime.now(timezone.utc))
        db.add(u)
        db.commit()
        p = CareerProfile(user_id=u.id)
        db.add(p)
        db.commit()
        exp = Experience(career_profile_id=p.id, title="Synthetic role", organization="Sample Company", start_date="2022", end_date="2025",
                         description="Led a synthetic team", source="manual", verified=True)
        db.add(exp)
        db.commit()
        pid, eid = p.id, exp.id
        db.close()
        return pid, eid

    # ---- helpers -------------------------------------------------------------------------------------------------------------
    def client(self):
        return TestClient(self.app, raise_server_exceptions=False)

    def _version(self, data):
        db = self.Session()
        v = ResumeVersion(career_profile_id=self.a_profile, resume_data=data)
        db.add(v)
        db.commit()
        vid = v.id
        db.close()
        return vid

    def _raw_version(self, label):
        return self._version({"name": "Synthetic A", "summary": f"Synthetic summary {label}."})

    def _link(self):
        res = self.client().post("/api/career/opportunities", headers=self.a,
                                 json={"title": "Two-session job", "job_url": "https://jobs.example-employer.com/2s/" + uuid.uuid4().hex[:8]})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["id"]

    def _approve(self, oid, vid):
        return self.client().put(f"/api/career/opportunities/{oid}/approval", headers=self.a, json={"approved_resume_version_id": vid})

    def _in_thread(self, name, fn):
        """Runs fn(client) on a new thread with the given name; returns (thread, result holder)."""
        holder = {}

        def run():
            try:
                holder["r"] = fn(self.client())
            except Exception as e:  # recorded, asserted by the caller
                holder["r"] = e
        t = threading.Thread(target=run, name=name)
        t.start()
        return t, holder

    def _wait_for_lock_wait(self, timeout=20.0):
        """Polls PostgreSQL until another session is blocked on a lock in this database. Returns how many were seen."""
        deadline = time.monotonic() + timeout
        seen = 0
        while time.monotonic() < deadline:
            with self.engine.connect() as c:
                # pg_stat_activity is a snapshot cached per transaction, so each poll uses its own connection and transaction;
                # polling inside one long transaction could keep reporting an early snapshot and miss the wait.
                seen = c.execute(sa.text("select count(*) from pg_stat_activity "
                                         "where datname = current_database() and wait_event_type = 'Lock'")).scalar()
            if seen:
                break
            time.sleep(0.05)
        return seen

    def _state(self, oid):
        with self.engine.connect() as c:
            row = c.execute(sa.text("select approved_resume_version_id, approved_resume_hash, application_id from opportunities where id = :i"),
                            {"i": oid}).one()
            docs = c.execute(sa.text("select resume_version_id, content_sha256, docx from opportunity_documents where opportunity_id = :i"),
                             {"i": oid}).all()
            app = None
            if row.application_id is not None:
                app = c.execute(sa.text("select resume_version_id from applications where id = :a"), {"a": row.application_id}).scalar()
        return {"approved": row.approved_resume_version_id, "hash": row.approved_resume_hash, "application_id": row.application_id,
                "application_version": app, "docs": docs}

    def _assert_consistent(self, oid):
        """Approval state, the frozen document and the record agree, and the bytes served are the stored bytes."""
        st = self._state(oid)
        if st["approved"] is None:
            self.assertEqual(st["docs"], [])
        else:
            self.assertEqual(len(st["docs"]), 1)
            doc_version, doc_sha, doc_bytes = st["docs"][0]
            self.assertEqual(doc_version, st["approved"])
            self.assertEqual(hashlib.sha256(bytes(doc_bytes)).hexdigest(), doc_sha)
            dl = self.client().get(f"/api/career/opportunities/{oid}/approved-document", headers=self.a)
            self.assertEqual(dl.status_code, 200, dl.text)
            self.assertEqual(dl.content, bytes(doc_bytes))
            self.assertEqual(dl.headers.get("X-Document-SHA256"), doc_sha)
        if st["application_id"] is not None:
            self.assertEqual(st["application_version"], st["approved"])   # an application only ever points at the approved version
        return st

    # ---- 1. a saved fact changes between preparation and commit (switch ON) ------------------------------------------------
    def test_saved_fact_change_between_preparation_and_commit_refuses_the_approval(self):
        db = self.Session()
        profile = db.get(CareerProfile, self.a_profile)
        content = {"name": "Synthetic A", "contact": "SYNTHETIC", "headline": "", "summary": "", "skills": [], "experience": [],
                   "education": [], "certifications": []}
        facts = rg.build_facts(db, profile)
        draft, review = rg.review_at_save(content, facts, "on")
        vid = self._version({**draft, "truth_review": review})
        db.close()
        with mock.patch.dict(os.environ, {GATE: "on"}):
            preview = self.client().get(f"/api/career/resume-versions/{vid}/preview", headers=self.a)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(self.client().post(f"/api/career/resume-versions/{vid}/signoff", headers=self.a,
                                                json={"finalized_hash": preview.json()["finalized_hash"]}).status_code, 200)
            oid = self._link()

            def change_fact():
                t, h = self._in_thread("B", lambda cl: cl.put(f"/api/career/experiences/{self.a_experience}", headers=self.a, json={
                    "title": "Synthetic role", "organization": "Sample Company", "description": "Changed on a second session.",
                    "start_date": "2022", "end_date": "2025"}))
                t.join()
                self.assertEqual(h["r"].status_code, 200, getattr(h["r"], "text", h["r"]))
            with _paused(opp, "_commit_approval", 1, change_fact):
                t, h = self._in_thread("A", lambda cl: cl.put(f"/api/career/opportunities/{oid}/approval", headers=self.a,
                                                             json={"approved_resume_version_id": vid}))
                t.join()
        self.assertEqual(h["r"].status_code, 409, h["r"].text)
        st = self._assert_consistent(oid)
        self.assertIsNone(st["approved"])
        self.assertEqual(st["docs"], [])

    # ---- 2. a newer approval arrives before a clear or no-op commits -----------------------------------------------------
    def test_newer_approval_before_a_clear_commit_is_not_erased(self):
        v1, v2 = self._raw_version("one"), self._raw_version("two")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        with _paused(opp, "_commit_approval", 1, lambda: self._run_second_approval(oid, v2)):
            t, h = self._in_thread("A", lambda cl: cl.put(f"/api/career/opportunities/{oid}/approval", headers=self.a,
                                                         json={"approved_resume_version_id": None}))
            t.join()
        self.assertEqual(h["r"].status_code, 409, getattr(h["r"], "text", h["r"]))
        st = self._assert_consistent(oid)
        self.assertEqual(st["approved"], v2)

    def test_newer_approval_before_a_no_op_commit_is_not_reported_as_unchanged(self):
        v1, v2 = self._raw_version("three"), self._raw_version("four")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        with _paused(opp, "_commit_approval", 1, lambda: self._run_second_approval(oid, v2)):
            t, h = self._in_thread("A", lambda cl: cl.put(f"/api/career/opportunities/{oid}/approval", headers=self.a,
                                                         json={"approved_resume_version_id": v1}))   # a no-op against v1
            t.join()
        self.assertEqual(h["r"].status_code, 409, getattr(h["r"], "text", h["r"]))
        st = self._assert_consistent(oid)
        self.assertEqual(st["approved"], v2)

    def _run_second_approval(self, oid, vid):
        t, h = self._in_thread("B", lambda cl: cl.put(f"/api/career/opportunities/{oid}/approval", headers=self.a,
                                                     json={"approved_resume_version_id": vid}))
        t.join()
        self.assertEqual(h["r"].status_code, 200, getattr(h["r"], "text", h["r"]))

    # ---- 3. application recording races approval ---------------------------------------------------------------------------
    def test_recording_before_an_approval_commit_wins_and_the_approval_is_refused(self):
        v1, v2 = self._raw_version("five"), self._raw_version("six")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        holder = {}

        def record_now():
            t, h = self._in_thread("B", lambda cl: cl.post(f"/api/career/opportunities/{oid}/record-application", headers=self.a,
                                                          json={"applied_on": "2026-11-11"}))
            t.join()
            holder["rec"] = h["r"]
        with _paused(opp, "_commit_approval", 1, record_now):
            t, h = self._in_thread("A", lambda cl: self._approve(oid, v2))
            t.join()
        self.assertEqual(holder["rec"].status_code, 200, holder["rec"].text)
        self.assertEqual(h["r"].status_code, 409, h["r"].text)
        st = self._assert_consistent(oid)
        self.assertEqual((st["approved"], st["application_version"]), (v1, v1))

    def test_an_approval_commit_holding_its_locks_makes_a_concurrent_recording_wait_then_see_the_new_approval(self):
        v1, v2 = self._raw_version("seven"), self._raw_version("eight")
        oid = self._link()
        self.assertEqual(self._approve(oid, v1).status_code, 200)
        observed = {}
        holder = {}

        def record_while_locked():
            t, h = self._in_thread("B", lambda cl: cl.post(f"/api/career/opportunities/{oid}/record-application", headers=self.a,
                                                          json={"applied_on": "2026-11-11"}))
            observed["lock_waits"] = self._wait_for_lock_wait()     # B is blocked on the row lock A holds
            holder["b"] = (t, h)
        with _paused(opp, "_approval_token", 2, record_while_locked):    # 2nd call = inside the commit phase, locks held
            t, h = self._in_thread("A", lambda cl: self._approve(oid, v2))
            t.join()
        bt, bh = holder["b"]
        bt.join()
        self.assertGreaterEqual(observed["lock_waits"], 1, "the recording never waited on the approval's lock")
        self.assertEqual(h["r"].status_code, 200, h["r"].text)
        self.assertEqual(bh["r"].status_code, 200, bh["r"].text)
        st = self._assert_consistent(oid)
        self.assertEqual((st["approved"], st["application_version"]), (v2, v2))


if __name__ == "__main__":
    unittest.main()
