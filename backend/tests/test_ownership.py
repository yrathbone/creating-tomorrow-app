"""Phase 2A: every signed-in person can reach only their own data.

These tests go through the REAL token check (auth/dependencies.get_current_user):
tokens are signed here with a throwaway RSA key and the module is pointed at that
key's public half, so nothing is stubbed out and nothing touches Cognito or the
network. Two synthetic people (A and B) are provisioned by their tokens' `sub`,
then every route is called directly over HTTP the way a hostile client would,
independent of anything the frontend does.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import time
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from jose import jwk, jwt
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.dependencies as deps
from auth.dependencies import get_current_user
from career.routes import router
from db import Base, get_db_session
from models import Application, CareerProfile, Certification, Education, Experience, ResumeVersion, ScanHistory, Skill, User

REGION, POOL, CLIENT = "us-test-1", "us-test-1_TESTPOOL", "test-app-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"
KID = "test-key-1"
SUB_A, SUB_B = "aaaaaaaa-0000-4000-8000-00000000000a", "bbbbbbbb-0000-4000-8000-00000000000b"


def _new_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    public_jwk = jwk.construct(public_pem, "RS256").to_dict()
    public_jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return private_pem, public_jwk


GOOD_PRIVATE, GOOD_JWK = _new_key()
OTHER_PRIVATE, _ = _new_key()  # a different key that Cognito (in this test) never published


def make_token(sub, *, key=None, kid=KID, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "sub": sub, "token_use": "access", "client_id": CLIENT,
        "scope": "aws.cognito.signin.user.admin", "username": sub, "iat": now, "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key or GOOD_PRIVATE, algorithm="RS256", headers={"kid": kid})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class OwnershipTestCase(unittest.TestCase):
    """Fresh in-memory database and a real-token app for every test."""

    def setUp(self):
        patches = [
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_jwks_cache", {"keys": [GOOD_JWK]}),
            # a key id we don't know would trigger a network refetch of Cognito's keys: serve the local keys instead
            mock.patch.object(deps, "_fetch_jwks", lambda: {"keys": [GOOD_JWK]}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

        app = FastAPI()
        app.include_router(router, prefix="/api/career")

        def session():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db_session] = session  # only the database is swapped; auth is the real thing
        self.client = TestClient(app)
        self.a = bearer(make_token(SUB_A))
        self.b = bearer(make_token(SUB_B))

    # -- helpers -------------------------------------------------------
    def call(self, method, path, who, **kw):
        return self.client.request(method, "/api/career" + path, headers=who, **kw)

    def onboard(self, who):
        self.assertEqual(self.call("POST", "/consent", who).status_code, 200)

    def profile_id_for(self, sub):
        with self.Session() as s:
            return s.query(CareerProfile).join(User).filter(User.cognito_sub == sub).one().id

    def seed_history_rows(self, sub):
        """Scans and resume versions come from AI routes; insert them directly."""
        pid = self.profile_id_for(sub)
        with self.Session() as s:
            scan = ScanHistory(career_profile_id=pid, scan_type="job_comparison", job_title=f"Secret job of {sub[:4]}", summary_text="s", result_data={})
            s.add(scan)
            s.commit()
            resume = ResumeVersion(
                career_profile_id=pid, scan_history_id=scan.id,
                resume_data={"name": f"Name of {sub[:4]}", "contact": "x@example.com", "summary": "", "skills": [], "experience": [], "education": [], "certifications": []},
            )
            s.add(resume)
            s.commit()
            return scan.id, resume.id

    def build_world(self):
        """A and B each own one record of every kind. Returns ids by owner."""
        ids = {}
        for who, label, sub in ((self.a, "A", SUB_A), (self.b, "B", SUB_B)):
            self.onboard(who)
            exp = self.call("POST", "/experiences", who, json={"title": f"Role {label}", "organization": f"Org {label}", "description": f"private-{label}"}).json()["id"]
            edu = self.call("POST", "/education", who, json={"institution": f"School {label}"}).json()["id"]
            cert = self.call("POST", "/certifications", who, json={"name": f"Cert {label}"}).json()["id"]
            skill = self.call("POST", "/skills", who, json={"name": f"Skill {label}", "experience_id": exp}).json()["id"]
            scan, resume = self.seed_history_rows(sub)
            app_ = self.call("POST", "/applications", who, json={"job_title": f"Applied {label}", "scan_history_id": scan, "resume_version_id": resume}).json()["id"]
            ids[label] = {"exp": exp, "edu": edu, "cert": cert, "skill": skill, "scan": scan, "resume": resume, "app": app_}
        return ids


class TokenVerification(OwnershipTestCase):
    def test_every_career_route_rejects_a_request_with_no_token(self):
        routes = [r for r in router.routes if isinstance(r, APIRoute)]
        # 43 routes through Phase 2A + 4 language routes + 2 profile routes (GET/PUT /profile) in Phase 2B = 49, + 2 resume-layout routes (GET/PUT /resume-layout, migration 0009) = 51
        self.assertEqual(len(routes), 52, "a route was added or removed: update this guard on purpose")  # 52 = 51 + POST /account/delete
        offenders = []
        for r in routes:
            method = sorted(r.methods - {"HEAD", "OPTIONS"})[0]
            path = r.path.replace("{experience_id}", "1").replace("{education_id}", "1").replace("{certification_id}", "1") \
                .replace("{skill_id}", "1").replace("{scan_history_id}", "1").replace("{resume_version_id}", "1").replace("{application_id}", "1").replace("{language_id}", "1")
            res = self.client.request(method, "/api/career" + path, json={})
            if res.status_code != 401:
                offenders.append((method, r.path, res.status_code))
        self.assertEqual(offenders, [])

    def test_every_career_route_rejects_a_garbage_token(self):
        routes = [r for r in router.routes if isinstance(r, APIRoute)]
        offenders = []
        for r in routes:
            method = sorted(r.methods - {"HEAD", "OPTIONS"})[0]
            path = r.path.replace("{experience_id}", "1").replace("{education_id}", "1").replace("{certification_id}", "1") \
                .replace("{skill_id}", "1").replace("{scan_history_id}", "1").replace("{resume_version_id}", "1").replace("{application_id}", "1").replace("{language_id}", "1")
            res = self.client.request(method, "/api/career" + path, headers=bearer("not.a.token"), json={})
            if res.status_code != 401:
                offenders.append((method, r.path, res.status_code))
        self.assertEqual(offenders, [])

    def test_bad_tokens_are_all_rejected(self):
        now = int(time.time())
        bad = {
            "signed with the wrong key": make_token(SUB_A, key=OTHER_PRIVATE),
            "unknown key id": make_token(SUB_A, kid="some-other-kid"),
            "expired": make_token(SUB_A, iat=now - 7200, exp=now - 3600),
            "wrong client": make_token(SUB_A, client_id="someone-elses-client"),
            "no client": make_token(SUB_A, client_id=None),
            "id token, not access": make_token(SUB_A, token_use="id"),
            "no token_use": make_token(SUB_A, token_use=None),
            "wrong issuer": make_token(SUB_A, iss="https://cognito-idp.us-test-1.amazonaws.com/us-test-1_OTHERPOOL"),
            "no subject": make_token(None),
            "empty subject": make_token(""),
            "garbage": "abc.def.ghi",
        }
        for label, token in bad.items():
            with self.subTest(label):
                self.assertEqual(self.call("GET", "/me", bearer(token)).status_code, 401, label)
        # a tampered payload on an otherwise valid token
        head, payload, sig = make_token(SUB_A).split(".")
        forged = ".".join([head, make_token(SUB_B).split(".")[1], sig])
        self.assertEqual(self.call("GET", "/me", bearer(forged)).status_code, 401)
        # and an unsigned ("alg": "none") token
        import base64, json
        b64 = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
        unsigned = b64({"alg": "none", "kid": KID}) + "." + b64({"iss": ISSUER, "sub": SUB_A, "token_use": "access", "client_id": CLIENT, "exp": now + 3600}) + "."
        self.assertEqual(self.call("GET", "/me", bearer(unsigned)).status_code, 401)
        with self.Session() as s:
            self.assertEqual(s.query(User).count(), 0, "a rejected token must never provision a user")

    def test_a_good_token_provisions_exactly_one_user_per_sub(self):
        for _ in range(3):
            self.assertEqual(self.call("GET", "/me", self.a).status_code, 200)
        self.assertEqual(self.call("GET", "/me", self.b).status_code, 200)
        with self.Session() as s:
            self.assertEqual(sorted(u.cognito_sub for u in s.query(User).all()), sorted([SUB_A, SUB_B]))

    def test_email_claims_do_not_decide_who_you_are(self):
        # A's token claiming to be B's email, and a stranger claiming A's email: identity is still the sub.
        self.onboard(self.a)
        self.call("POST", "/experiences", self.a, json={"title": "A job", "organization": "A org"})
        claims_b_email = bearer(make_token(SUB_A, email="b@example.com", **{"cognito:username": "b@example.com"}))
        self.assertEqual([e["title"] for e in self.call("GET", "/experiences", claims_b_email).json()], ["A job"])
        stranger = bearer(make_token("cccccccc-0000-4000-8000-00000000000c", email="a@example.com", username="a@example.com"))
        self.assertEqual(self.call("GET", "/me", stranger).status_code, 200)
        self.assertEqual(self.call("GET", "/experiences", stranger).status_code, 404)  # no profile: not A's
        with self.Session() as s:
            self.assertEqual(s.query(User).count(), 2)
            self.assertTrue(all(u.email is None for u in s.query(User).all()), "email is never read from a token")


class Isolation(OwnershipTestCase):
    def test_ownership_comes_from_the_token_not_the_request_body(self):
        self.onboard(self.a)
        self.onboard(self.b)
        b_profile = self.profile_id_for(SUB_B)
        injected = {"user_id": 99, "cognito_sub": SUB_B, "career_profile_id": b_profile, "owner_id": 2, "sub": SUB_B, "email": "b@example.com"}
        bodies = {
            "/experiences": {"title": "Injected", "organization": "Org"},
            "/education": {"institution": "Injected U"},
            "/certifications": {"name": "Injected cert"},
            "/skills": {"name": "Injected skill"},
            "/applications": {"job_title": "Injected app"},
        }
        for path, body in bodies.items():
            with self.subTest(path):
                res = self.call("POST", path, self.a, json={**body, **injected})
                self.assertIn(res.status_code, (200, 422), res.text)  # ignored extras (200) or rejected (422): never honored
        with self.Session() as s:
            a_profile = self.profile_id_for(SUB_A)
            for model in (Experience, Education, Certification, Skill, Application):
                self.assertEqual(s.query(model).filter_by(career_profile_id=b_profile).count(), 0, f"{model.__name__} landed on B")
            self.assertGreaterEqual(s.query(Experience).filter_by(career_profile_id=a_profile).count(), 1)
        for path in bodies:
            self.assertEqual(self.call("GET", path, self.b).json(), [], path)
        a_user = self.call("GET", "/me", self.a).json()
        self.assertIsNone(a_user["email"])

    def test_b_cannot_see_change_or_delete_a_record_even_with_its_id(self):
        ids = self.build_world()
        a = ids["A"]
        attempts = [
            ("PUT", f"/experiences/{a['exp']}", {"title": "Hacked", "organization": "Hacked"}),
            ("DELETE", f"/experiences/{a['exp']}", None),
            ("PUT", f"/education/{a['edu']}", {"institution": "Hacked"}),
            ("DELETE", f"/education/{a['edu']}", None),
            ("PUT", f"/certifications/{a['cert']}", {"name": "Hacked"}),
            ("DELETE", f"/certifications/{a['cert']}", None),
            ("PUT", f"/skills/{a['skill']}", {"name": "Hacked"}),
            ("DELETE", f"/skills/{a['skill']}", None),
            ("DELETE", f"/scan-history/{a['scan']}", None),
            ("DELETE", f"/resume-versions/{a['resume']}", None),
            ("GET", f"/resume-versions/{a['resume']}/download", None),
            ("PUT", f"/applications/{a['app']}", {"job_title": "Hacked"}),
            ("DELETE", f"/applications/{a['app']}", None),
        ]
        self.assertEqual(len(attempts), 13, "all 13 ID-based routes")
        for method, path, body in attempts:
            with self.subTest(f"{method} {path}"):
                kw = {"json": body} if body is not None else {}
                self.assertEqual(self.call(method, path, self.b, **kw).status_code, 404)
        # ...and A's data is exactly as it was
        with self.Session() as s:
            self.assertEqual(s.get(Experience, a["exp"]).title, "Role A")
            self.assertEqual(s.get(Education, a["edu"]).institution, "School A")
            self.assertEqual(s.get(Certification, a["cert"]).name, "Cert A")
            self.assertEqual(s.get(Skill, a["skill"]).name, "Skill A")
            self.assertIsNotNone(s.get(ScanHistory, a["scan"]))
            self.assertIsNotNone(s.get(ResumeVersion, a["resume"]))
            self.assertEqual(s.get(Application, a["app"]).job_title, "Applied A")

    def test_lists_and_export_only_contain_the_callers_own_records(self):
        ids = self.build_world()
        for path in ("/experiences", "/education", "/certifications", "/skills", "/scan-history", "/resume-versions", "/applications"):
            with self.subTest(path):
                a_rows = self.call("GET", path, self.a).json()
                b_rows = self.call("GET", path, self.b).json()
                self.assertEqual(len(a_rows), 1)
                self.assertEqual(len(b_rows), 1)
                self.assertNotEqual(a_rows[0]["id"], b_rows[0]["id"])
        export_b = self.call("GET", "/export", self.b)
        self.assertEqual(export_b.status_code, 200)
        text_b = export_b.text
        for secret in ("Role A", "Org A", "private-A", "School A", "Cert A", "Skill A", "Secret job of aaaa", "Name of aaaa", "Applied A"):
            self.assertNotIn(secret, text_b, f"B's export leaked {secret!r}")
        self.assertIn("Role B", text_b)
        text_a = self.call("GET", "/export", self.a).text
        self.assertNotIn("Role B", text_a)
        self.assertIn("Role A", text_a)

    def test_non_owned_cross_references_in_a_request_body_are_rejected(self):
        ids = self.build_world()
        a, b = ids["A"], ids["B"]
        # B points its own records at A's role / scan / resume
        self.assertEqual(self.call("POST", "/skills", self.b, json={"name": "Stolen link", "experience_id": a["exp"]}).status_code, 400)
        self.assertEqual(self.call("PUT", f"/skills/{b['skill']}", self.b, json={"name": "Skill B", "experience_id": a["exp"]}).status_code, 400)
        self.assertEqual(self.call("POST", "/applications", self.b, json={"job_title": "X", "scan_history_id": a["scan"]}).status_code, 400)
        self.assertEqual(self.call("POST", "/applications", self.b, json={"job_title": "X", "resume_version_id": a["resume"]}).status_code, 400)
        self.assertEqual(self.call("PUT", f"/applications/{b['app']}", self.b, json={"job_title": "X", "scan_history_id": a["scan"]}).status_code, 400)
        # building a resume "for" A's scan is refused before any AI call
        res = self.call("POST", "/job-build-resume", self.b, json={"job_description": "jd", "name": "B", "contact": "c", "scan_history_id": a["scan"]})
        self.assertEqual(res.status_code, 400, res.text)
        # resume-save merging into A's role id must NOT touch A's role
        res = self.call("POST", "/resume-save", self.b, json={"roles": [{"title": "Hijack", "organization": "Org", "bullets": ["added by B"], "existing_id": a["exp"]}]})
        self.assertEqual(res.status_code, 200, res.text)
        with self.Session() as s:
            self.assertEqual(s.get(Experience, a["exp"]).description, "private-A")
            self.assertEqual(s.query(Experience).filter_by(career_profile_id=self.profile_id_for(SUB_B), title="Hijack").count(), 1)
        # skill-scan-save with A's role id is refused
        res = self.call("POST", "/skill-scan-save", self.b, json={"confirmed_facts": [{"name": "Linked", "experience_id": a["exp"]}]})
        self.assertEqual(res.status_code, 400, res.text)

    def test_same_user_crud_still_works(self):
        who = self.a
        self.onboard(who)
        exp = self.call("POST", "/experiences", who, json={"title": "T", "organization": "O"}).json()["id"]
        self.assertEqual(self.call("PUT", f"/experiences/{exp}", who, json={"title": "T2", "organization": "O"}).json()["title"], "T2")
        skill = self.call("POST", "/skills", who, json={"name": "S", "experience_id": exp}).json()
        self.assertEqual(skill["experience_id"], exp)
        edu = self.call("POST", "/education", who, json={"institution": "U"}).json()["id"]
        self.assertEqual(self.call("PUT", f"/education/{edu}", who, json={"institution": "U2"}).json()["institution"], "U2")
        cert = self.call("POST", "/certifications", who, json={"name": "C"}).json()["id"]
        self.assertEqual(self.call("PUT", f"/certifications/{cert}", who, json={"name": "C2"}).json()["name"], "C2")
        scan, resume = self.seed_history_rows(SUB_A)
        app_ = self.call("POST", "/applications", who, json={"job_title": "J", "scan_history_id": scan, "resume_version_id": resume}).json()
        self.assertEqual((app_["scan_history_id"], app_["resume_version_id"]), (scan, resume))
        self.assertEqual(self.call("PUT", f"/applications/{app_['id']}", who, json={"job_title": "J", "status": "interview"}).json()["status"], "interview")
        self.assertEqual(self.call("GET", f"/resume-versions/{resume}/download", who).status_code, 200)
        self.assertEqual(len(self.call("GET", "/scan-history", who).json()), 1)
        self.assertEqual(len(self.call("GET", "/resume-versions", who).json()), 1)
        for path in (f"/applications/{app_['id']}", f"/skills/{skill['id']}", f"/certifications/{cert}", f"/education/{edu}",
                     f"/resume-versions/{resume}", f"/scan-history/{scan}", f"/experiences/{exp}"):
            self.assertEqual(self.call("DELETE", path, who).status_code, 200, path)
        for path in ("/experiences", "/education", "/certifications", "/skills", "/scan-history", "/resume-versions", "/applications"):
            self.assertEqual(self.call("GET", path, who).json(), [], path)


class _RacyDB:
    """Wraps a real session but makes the FIRST User lookup miss, as if another request had not
    created the user yet - the interleaving two simultaneous first logins produce."""

    def __init__(self, real):
        self._real, self._first = real, True

    def query(self, *a, **k):
        outer, q = self, self._real.query(*a, **k)

        class _Query:
            def filter_by(self_, **kw):
                inner = q.filter_by(**kw)

                class _Filtered:
                    def one_or_none(self__):
                        if outer._first:
                            outer._first = False
                            return None
                        return inner.one_or_none()

                    def __getattr__(self__, n):
                        return getattr(inner, n)
                return _Filtered()

            def __getattr__(self_, n):
                return getattr(q, n)
        return _Query()

    def __getattr__(self, name):
        return getattr(self._real, name)


class UserResolutionHardening(OwnershipTestCase):
    """Phase 2A hardening of auth/dependencies.get_current_user (first-login race, deleted users)."""

    def test_first_login_race_resolves_to_the_one_existing_user(self):
        with self.Session() as s:
            s.add(User(cognito_sub=SUB_A))
            s.commit()
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=make_token(SUB_A))
        with self.Session() as s:
            user = get_current_user(credentials=creds, db=_RacyDB(s))
            self.assertEqual(user.cognito_sub, SUB_A)
        with self.Session() as s:
            self.assertEqual(s.query(User).filter_by(cognito_sub=SUB_A).count(), 1)

    def test_a_soft_deleted_user_is_refused_even_with_a_valid_token(self):
        self.assertEqual(self.call("GET", "/me", self.a).status_code, 200)
        from datetime import datetime, timezone
        with self.Session() as s:
            s.query(User).filter_by(cognito_sub=SUB_A).one().deleted_at = datetime.now(timezone.utc)
            s.commit()
        self.assertEqual(self.call("GET", "/me", self.a).status_code, 403)
        self.assertEqual(self.call("GET", "/experiences", self.a).status_code, 403)
        # a deleted user must not be quietly re-provisioned as a fresh account
        with self.Session() as s:
            self.assertEqual(s.query(User).filter_by(cognito_sub=SUB_A).count(), 1)
        # other people are unaffected
        self.assertEqual(self.call("GET", "/me", self.b).status_code, 200)


if __name__ == "__main__":
    unittest.main()
