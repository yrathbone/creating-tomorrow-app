"""Signed-in authorization checks with a TEST signing key (C-52 F08). Offline, SQLite, synthetic members.

These tests run the REAL token verification in auth/dependencies.py: RS256 signature, issuer, expiry, token_use and client_id.
Only the public key list is replaced, by a key generated during the test run. No key is stored in the repository and no
Cognito call is made. Production Cognito is never contacted.
"""
import base64
import json
import time
import unittest
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.dependencies as deps
from career.opportunities import router as opportunities_router
from career.routes import router as career_router
from db import Base, get_db_session
from models import CareerProfile, ResumeVersion, User

REGION = "us-east-2"
POOL = "us-east-2_HARNESS1"
CLIENT = "harnessclientid0000000000000"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
KID = "harness-kid-1"


def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private_key):
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return jwk


def access_token(key, sub, **over):
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": sub, "client_id": CLIENT, "token_use": "access", "username": sub,
              "iat": now, "exp": now + 3600, "scope": "openid"}
    claims.update(over)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


class SignedInAuthorization(unittest.TestCase):
    def setUp(self):
        self.key = _new_key()
        self.other_key = _new_key()
        patches = [
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_jwks_cache", {"keys": [_jwk(self.key)]}),
            mock.patch.object(deps, "_jwks_fetched_at", None),
            mock.patch.object(deps, "_jwks_last_attempt", time.monotonic()),
            mock.patch.dict("os.environ", {"CT_OPPORTUNITIES_ENABLED": "1"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
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
        self.a = access_token(self.key, "synthetic-member-a")
        self.b = access_token(self.key, "synthetic-member-b")

    def auth(self, token):
        return {"Authorization": "Bearer " + token}

    def _profile(self, sub):
        """A synthetic member with a career profile (what the consent step creates in the product)."""
        db = self.Session()
        u = User(cognito_sub=sub)
        db.add(u)
        db.commit()
        db.add(CareerProfile(user_id=u.id))
        db.commit()
        pid = db.query(CareerProfile.id).filter_by(user_id=u.id).scalar()
        db.close()
        return pid

    def test_a_valid_signed_token_is_accepted_for_a_member_with_a_profile(self):
        self._profile("synthetic-member-a")
        r = self.client.get("/api/career/opportunities", headers=self.auth(self.a))
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_valid_token_for_a_member_without_a_profile_is_told_to_consent_first(self):
        r = self.client.get("/api/career/opportunities", headers=self.auth(self.a))
        self.assertEqual(r.status_code, 404, r.text)
        self.assertIn("consent", r.json()["detail"])

    def test_no_token_is_refused(self):
        r = self.client.get("/api/career/opportunities")
        self.assertIn(r.status_code, (401, 403))

    def test_an_unsigned_token_is_refused(self):
        unsigned = jwt.encode({"iss": ISSUER, "sub": "x", "client_id": CLIENT, "token_use": "access", "exp": int(time.time()) + 600},
                              key=None, algorithm="none")
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(unsigned)).status_code, 401)

    def test_a_token_signed_with_another_key_is_refused(self):
        forged = access_token(self.other_key, "synthetic-member-a")
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(forged)).status_code, 401)

    def test_a_tampered_payload_is_refused(self):
        head, body, sig = self.a.split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=="))
        claims["sub"] = "synthetic-member-b"
        new_body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(f"{head}.{new_body}.{sig}")).status_code, 401)

    def test_a_wrong_issuer_is_refused(self):
        bad = access_token(self.key, "synthetic-member-a", iss="https://cognito-idp.us-east-2.amazonaws.com/us-east-2_OTHER")
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(bad)).status_code, 401)

    def test_an_expired_token_is_refused(self):
        old = access_token(self.key, "synthetic-member-a", exp=int(time.time()) - 60, iat=int(time.time()) - 3600)
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(old)).status_code, 401)

    def test_an_id_token_is_not_accepted_for_the_api(self):
        idt = access_token(self.key, "synthetic-member-a", token_use="id")
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(idt)).status_code, 401)

    def test_a_token_for_another_application_is_refused(self):
        other_app = access_token(self.key, "synthetic-member-a", client_id="someone-else-client")
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(other_app)).status_code, 401)

    def test_member_b_cannot_see_change_or_download_member_a_link_or_document(self):
        pid = self._profile("synthetic-member-a")
        self._profile("synthetic-member-b")
        db = self.Session()
        v = ResumeVersion(career_profile_id=pid, resume_data={"name": "Synthetic A", "summary": "Sample."})
        db.add(v)
        db.commit()
        vid = v.id
        db.close()
        made = self.client.post("/api/career/opportunities", headers=self.auth(self.a),
                                json={"title": "Analyst", "employer": "Sample", "job_url": "https://jobs.example-employer.com/postings/a1"}).json()
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", headers=self.auth(self.a),
                                         json={"approved_resume_version_id": vid}).status_code, 200)
        self.assertEqual(self.client.get("/api/career/opportunities", headers=self.auth(self.b)).json(), [])
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}", headers=self.auth(self.b),
                                         json={"title": "Hijack", "job_url": "https://jobs.example-employer.com/postings/a1"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/career/opportunities/{made['id']}", headers=self.auth(self.b)).status_code, 404)
        self.assertEqual(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document", headers=self.auth(self.b)).status_code, 404)
        self.assertEqual(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document", headers=self.auth(self.a)).status_code, 200)


if __name__ == "__main__":
    unittest.main()
