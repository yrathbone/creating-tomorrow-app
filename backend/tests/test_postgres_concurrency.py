"""C-52 PostgreSQL concurrency, isolation, locking, deletion and switch checks (round 8).

Runs ONLY against the configured disposable self-hosted C-52 test database (tests/harness/pg_test_config.py). Synthetic members only.
All tables live in a dedicated schema created for this run and dropped at the end. Real token verification is used
(the test signing key is generated at run time, as in test_signed_in_harness.py). Nothing is printed except results.
The target server major version is PostgreSQL 16.
"""
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
    from career.opportunities import router as opportunities_router
    from career.routes import router as career_router
    from db import Base, get_db_session
    from models import CareerProfile, Experience, ResumeVersion, User
    from tests.test_signed_in_harness import CLIENT, POOL, REGION, _jwk, _new_key, access_token


@unittest.skipUnless(VERIFIED is not None, "NOT RUN: " + SKIP_REASON)
class PostgresConcurrencyIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "c52_test_" + uuid.uuid4().hex[:10]
        url = URL.replace("postgresql://", "postgresql+psycopg://", 1)
        admin = sa.create_engine(url)
        with admin.begin() as c:
            c.execute(sa.text(f'create schema "{cls.schema}"'))
        admin.dispose()
        cls.engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={cls.schema}"}, pool_size=12, max_overflow=4)
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)
        cls.key = _new_key()
        # Synthetic identifiers. A, B and CAP are on the founder-only allowlist; C is deliberately not.
        cls.a_sub, cls.b_sub = "pg-synthetic-a-" + uuid.uuid4().hex[:6], "pg-synthetic-b-" + uuid.uuid4().hex[:6]
        cls.cap_sub = "pg-synthetic-cap-" + uuid.uuid4().hex[:6]
        cls.c_sub = "pg-synthetic-c-" + uuid.uuid4().hex[:6]
        allowed = ",".join([cls.a_sub, cls.b_sub, cls.cap_sub])
        cls._patches = [
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_jwks_cache", {"keys": [_jwk(cls.key)]}),
            mock.patch.object(deps, "_jwks_fetched_at", None),
            mock.patch.object(deps, "_jwks_last_attempt", time.monotonic()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": allowed}),
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
        cls.cap = {"Authorization": "Bearer " + access_token(cls.key, cls.cap_sub)}
        cls.c = {"Authorization": "Bearer " + access_token(cls.key, cls.c_sub)}
        cls.a_resume = cls._seed(cls.a_sub, "Synthetic A")
        cls._seed(cls.b_sub, "Synthetic B")
        cls._seed(cls.cap_sub, "Synthetic Cap")
        cls._seed(cls.c_sub, "Synthetic C (not allowlisted)")

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
        db.add(Experience(career_profile_id=p.id, title="Synthetic role", organization="Sample Company", start_date="2022", end_date="2025",
                          description="Led a synthetic team", source="manual", verified=True))
        v = ResumeVersion(career_profile_id=p.id, resume_data={"name": name, "summary": "Synthetic summary."})
        db.add(v)
        db.commit()
        vid = v.id
        db.close()
        return vid

    def client(self):
        return TestClient(self.app, raise_server_exceptions=False)

    def _run_threads(self, calls):
        results = [None] * len(calls)

        def worker(i, fn):
            try:
                results[i] = fn(self.client())
            except Exception as e:  # recorded, asserted below
                results[i] = e

        threads = [threading.Thread(target=worker, args=(i, fn)) for i, fn in enumerate(calls)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def _count(self, sql, **params):
        with self.engine.connect() as c:
            return c.execute(sa.text(sql), params).scalar()

    # ------------------------------------------------------------------ server version and identity
    def test_server_identity_is_the_expected_test_branch_and_tls(self):
        self.assertEqual(VERIFIED["database"], EXPECTED_DB)
        self.assertTrue(VERIFIED["tls"])
        print(f"\n[pg] server major version {VERIFIED['server_major_version']}; PostgreSQL 16 is NOT established by this run.")

    # ------------------------------------------------------------------ 200-link cap under concurrency
    def test_200_link_cap_holds_under_ten_simultaneous_creates(self):
        # Dedicated member (CAP) so the count starts at zero regardless of test order.
        c = self.client()
        for i in range(199):
            r = c.post("/api/career/opportunities", headers=self.cap, json={"title": "Seed", "job_url": f"https://jobs.example-employer.com/cap/{i}"})
            self.assertEqual(r.status_code, 200, r.text)
        calls = [(lambda i: (lambda cl: cl.post("/api/career/opportunities", headers=self.cap, json={"title": "Race", "job_url": f"https://jobs.example-employer.com/race/{i}"})))(i) for i in range(10)]
        results = self._run_threads(calls)
        codes = sorted(r.status_code if not isinstance(r, Exception) else "exc" for r in results)
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(codes.count(409), 9, codes)
        self.assertEqual(self._count("select count(*) from opportunities o join career_profiles p on p.id = o.career_profile_id join users u on u.id = p.user_id where u.cognito_sub = :s", s=self.cap_sub), 200)

    # ------------------------------------------------------------------ duplicate links under concurrency
    def test_duplicate_link_is_created_once_under_ten_simultaneous_saves(self):
        url = "https://jobs.example-employer.com/dup/" + uuid.uuid4().hex[:6]
        calls = [(lambda cl: cl.post("/api/career/opportunities", headers=self.b, json={"title": "Dup", "job_url": url})) for _ in range(10)]
        results = self._run_threads(calls)
        codes = sorted(r.status_code if not isinstance(r, Exception) else "exc" for r in results)
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(codes.count(409), 9, codes)

    # ------------------------------------------------------------------ approval, editing and recording together
    def test_concurrent_edit_approve_and_record_leave_a_consistent_record(self):
        c = self.client()
        made = c.post("/api/career/opportunities", headers=self.a, json={"title": "Race job", "job_url": "https://jobs.example-employer.com/combo/" + uuid.uuid4().hex[:6]}).json()
        oid = made["id"]
        c.put(f"/api/career/opportunities/{oid}/approval", headers=self.a, json={"approved_resume_version_id": self.a_resume})
        calls = []
        for i in range(4):
            calls.append((lambda i: (lambda cl: cl.put(f"/api/career/opportunities/{oid}/approval", headers=self.a, json={"approved_resume_version_id": self.a_resume})))(i))
            calls.append((lambda i: (lambda cl: cl.post(f"/api/career/opportunities/{oid}/record-application", headers=self.a, json={"applied_on": "2026-11-11"})))(i))
        results = self._run_threads(calls)
        codes = [r.status_code if not isinstance(r, Exception) else "exc" for r in results]
        self.assertNotIn("exc", codes, codes)
        self.assertNotIn(500, codes, codes)
        # Exactly one application and one stored document for the job, each pointing at the approved version.
        self.assertEqual(self._count("select count(*) from applications a join opportunities o on o.application_id = a.id where o.id = :i", i=oid), 1)
        app_id = self._count("select application_id from opportunities where id = :i", i=oid)
        self.assertIsNotNone(app_id)
        self.assertEqual(self._count("select resume_version_id from applications where id = :a", a=app_id), self.a_resume)
        self.assertEqual(self._count("select count(*) from opportunity_documents where opportunity_id = :i", i=oid), 1)
        self.assertEqual(self._count("select resume_version_id from opportunity_documents where opportunity_id = :i", i=oid), self.a_resume)
        # The stored document is the one the approval fingerprint was taken from: the download carries its stored hash.
        stored_hash = self._count("select content_sha256 from opportunity_documents where opportunity_id = :i", i=oid)
        dl = c.get(f"/api/career/opportunities/{oid}/approved-document", headers=self.a)
        self.assertEqual(dl.status_code, 200, dl.text)
        self.assertEqual(dl.headers.get("X-Document-SHA256"), stored_hash)
        approved_hash = self._count("select approved_resume_hash from opportunities where id = :i", i=oid)
        self.assertIsNotNone(approved_hash)

    # ------------------------------------------------------------------ cross-member isolation
    def test_member_b_cannot_read_change_or_download_member_a_records(self):
        c = self.client()
        made = c.post("/api/career/opportunities", headers=self.a, json={"title": "A only", "job_url": "https://jobs.example-employer.com/iso/" + uuid.uuid4().hex[:6]}).json()
        oid = made["id"]
        c.put(f"/api/career/opportunities/{oid}/approval", headers=self.a, json={"approved_resume_version_id": self.a_resume})
        rec = c.post(f"/api/career/opportunities/{oid}/record-application", headers=self.a, json={"applied_on": "2026-11-11"}).json()
        app_id = rec["application"]["id"]
        # B is allowlisted, so B's refusals below come from ownership checks, not from the allowlist.
        self.assertEqual(c.get("/api/career/opportunities", headers=self.b).status_code, 200)
        self.assertNotIn(oid, [x["id"] for x in c.get("/api/career/opportunities", headers=self.b).json()])
        self.assertEqual(c.put(f"/api/career/opportunities/{oid}", headers=self.b, json={"title": "x", "job_url": "https://jobs.example-employer.com/iso/z"}).status_code, 404)
        self.assertEqual(c.delete(f"/api/career/opportunities/{oid}", headers=self.b).status_code, 404)
        self.assertEqual(c.get(f"/api/career/opportunities/{oid}/approved-document", headers=self.b).status_code, 404)
        self.assertEqual(c.get(f"/api/career/applications/{app_id}/approved-document", headers=self.b).status_code, 404)
        self.assertEqual(c.put(f"/api/career/applications/{app_id}", headers=self.b, json={"job_title": "x", "status": "applied", "resume_version_id": None}).status_code, 404)

    # ------------------------------------------------------------------ recorded résumé reference lock on PostgreSQL
    def test_recorded_application_reference_stays_locked_on_postgresql(self):
        c = self.client()
        made = c.post("/api/career/opportunities", headers=self.a, json={"title": "Lock job", "job_url": "https://jobs.example-employer.com/lock/" + uuid.uuid4().hex[:6]}).json()
        oid = made["id"]
        c.put(f"/api/career/opportunities/{oid}/approval", headers=self.a, json={"approved_resume_version_id": self.a_resume})
        app_id = c.post(f"/api/career/opportunities/{oid}/record-application", headers=self.a, json={"applied_on": "2026-11-11"}).json()["application"]["id"]
        r = c.put(f"/api/career/applications/{app_id}", headers=self.a, json={"job_title": "Lock job", "status": "applied", "resume_version_id": None})
        self.assertEqual(r.status_code, 409, r.text)

    # ------------------------------------------------------------------ export and account deletion on PostgreSQL
    def test_export_and_account_deletion_remove_saved_links_documents_and_applications(self):
        sub = "pg-synthetic-del-" + uuid.uuid4().hex[:6]
        headers = {"Authorization": "Bearer " + access_token(self.key, sub)}
        vid = self._seed(sub, "Synthetic Delete")
        c = self.client()
        made = c.post("/api/career/opportunities", headers=headers, json={"title": "Delete me", "job_url": "https://jobs.example-employer.com/del/" + uuid.uuid4().hex[:6]}).json()
        c.put(f"/api/career/opportunities/{made['id']}/approval", headers=headers, json={"approved_resume_version_id": vid})
        c.post(f"/api/career/opportunities/{made['id']}/record-application", headers=headers, json={"applied_on": "2026-11-11"})
        exp = c.get("/api/career/export", headers=headers).json()
        self.assertEqual(len(exp["opportunities"]), 1)
        self.assertEqual(len(exp["approved_documents"]), 1)
        r = c.post("/api/career/account/delete", headers=headers, json={"confirm": "DELETE"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._count("select count(*) from users where cognito_sub = :s", s=sub), 0)
        self.assertEqual(self._count("select count(*) from opportunity_documents d join career_profiles p on p.id = d.career_profile_id join users u on u.id = p.user_id where u.cognito_sub = :s", s=sub), 0)

    # ------------------------------------------------------------------ feature switch OFF
    # ------------------------------------------------------------------ authorization denial (allowlist), not ownership
    def test_signed_in_member_not_on_the_allowlist_is_denied_on_every_route(self):
        c = self.client()
        made = c.post("/api/career/opportunities", headers=self.a, json={"title": "A for denial", "job_url": "https://jobs.example-employer.com/deny/" + uuid.uuid4().hex[:6]}).json()
        oid = made["id"]
        denied = [
            c.get("/api/career/opportunities", headers=self.c),
            c.post("/api/career/opportunities", headers=self.c, json={"title": "x", "job_url": "https://jobs.example-employer.com/deny/c"}),
            c.get(f"/api/career/opportunities/{oid}/approved-document", headers=self.c),
            c.delete("/api/career/opportunities?state=dismissed", headers=self.c),
        ]
        for r in denied:
            self.assertEqual(r.status_code, 404, r.text)
        # Same answer as a switched-off feature, so the feature is not revealed to a non-member.
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": ""}):
            off = c.get("/api/career/opportunities", headers=self.a)
        self.assertEqual((denied[0].status_code, denied[0].json()), (off.status_code, off.json()))
        self.assertEqual(self._count("select count(*) from opportunities o join career_profiles p on p.id = o.career_profile_id join users u on u.id = p.user_id where u.cognito_sub = :s", s=self.c_sub), 0)

    def test_feature_switch_off_returns_404_on_postgresql(self):
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": ""}):
            self.assertEqual(self.client().get("/api/career/opportunities", headers=self.a).status_code, 404)


if __name__ == "__main__":
    unittest.main()
