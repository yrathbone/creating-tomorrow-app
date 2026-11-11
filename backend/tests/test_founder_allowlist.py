"""C-52 founder-only access: server-side allowlist, default deny (offline, SQLite, synthetic accounts, real token checks)."""
import os
import time
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.dependencies as deps
from career.opportunities import router as opportunities_router
from career.routes import router as career_router
from db import Base, get_db_session
from models import CareerProfile, User
from tests.test_signed_in_harness import CLIENT, POOL, REGION, _jwk, _new_key, access_token

FOUNDER = "synthetic-founder-account"
OTHER = "synthetic-other-account"


class FounderAllowlist(unittest.TestCase):
    def setUp(self):
        self.key = _new_key()
        patches = [
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_jwks_cache", {"keys": [_jwk(self.key)]}),
            mock.patch.object(deps, "_jwks_fetched_at", None),
            mock.patch.object(deps, "_jwks_last_attempt", time.monotonic()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": FOUNDER}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        for sub in (FOUNDER, OTHER):
            db = self.Session()
            u = User(cognito_sub=sub)
            db.add(u)
            db.commit()
            db.add(CareerProfile(user_id=u.id))
            db.commit()
            db.close()
        app = FastAPI()
        app.include_router(career_router, prefix="/api/career")
        app.include_router(opportunities_router, prefix="/api/career")

        def session():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db_session] = session
        self.client = TestClient(app, raise_server_exceptions=False)
        self.founder = {"Authorization": "Bearer " + access_token(self.key, FOUNDER)}
        self.other = {"Authorization": "Bearer " + access_token(self.key, OTHER)}

    def test_the_allowed_founder_account_can_use_my_opportunities(self):
        r = self.client.get("/api/career/opportunities", headers=self.founder)
        self.assertEqual(r.status_code, 200, r.text)

    def test_any_other_signed_in_account_is_denied_on_every_saved_job_route(self):
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.other).status_code, 404)
        self.assertEqual(self.client.post("/api/career/opportunities", headers=self.other,
                                          json={"title": "x", "job_url": "https://jobs.example-employer.com/a"}).status_code, 404)
        self.assertEqual(self.client.get("/api/career/opportunities/1/approved-document", headers=self.other).status_code, 404)
        self.assertEqual(self.client.delete("/api/career/opportunities?state=dismissed", headers=self.other).status_code, 404)

    def test_denial_looks_the_same_as_a_switched_off_feature(self):
        denied = self.client.get("/api/career/opportunities", headers=self.other)
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": ""}):
            off = self.client.get("/api/career/opportunities", headers=self.founder)
        self.assertEqual((denied.status_code, denied.json()), (off.status_code, off.json()))

    def test_default_deny_when_the_allowlist_is_empty(self):
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ALLOWED_SUBS": ""}):
            self.assertEqual(self.client.get("/api/career/opportunities", headers=self.founder).status_code, 404)
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ALLOWED_SUBS": ""}):
            os.environ.pop("CT_OPPORTUNITIES_ALLOWED_SUBS", None)
            self.assertEqual(self.client.get("/api/career/opportunities", headers=self.founder).status_code, 404)

    def test_disabling_the_feature_blocks_the_founder_too(self):
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": ""}):
            self.assertEqual(self.client.get("/api/career/opportunities", headers=self.founder).status_code, 404)
            self.assertEqual(self.client.get("/api/career/opportunities", headers=self.other).status_code, 404)

    def test_removing_the_founder_from_the_allowlist_blocks_the_founder(self):
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ALLOWED_SUBS": OTHER}):
            self.assertEqual(self.client.get("/api/career/opportunities", headers=self.founder).status_code, 404)
            self.assertEqual(self.client.get("/api/career/opportunities", headers=self.other).status_code, 200)


if __name__ == "__main__":
    unittest.main()
