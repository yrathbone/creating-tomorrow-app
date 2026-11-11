"""C-52 round 7: the saved-job journey through the REAL routes, with the deterministic AI stub (synthetic data, offline).

Save -> compare -> build -> approve -> approved-document download -> record application -> tracker lock.
The stub replaces only the model's answer. Every route, check and authorization step is the real code.
"""
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
from models import CareerProfile, Education, Experience, Skill, User
from tests.harness import ai_stub
from tests.test_signed_in_harness import CLIENT, ISSUER, POOL, REGION, _jwk, _new_key, access_token, KID  # noqa: F401

POSTING = (
    "Customer Service Lead at Sample Employer. You will lead a team of agents, handle customer escalations, "
    "use Zendesk daily and work with Salesforce for account history. Requires team leadership experience."
)


class AiStubJourney(unittest.TestCase):
    def setUp(self):
        self.key = _new_key()
        patches = [
            mock.patch.object(deps, "COGNITO_REGION", REGION),
            mock.patch.object(deps, "COGNITO_USER_POOL_ID", POOL),
            mock.patch.object(deps, "COGNITO_APP_CLIENT_ID", CLIENT),
            mock.patch.object(deps, "_jwks_cache", {"keys": [_jwk(self.key)]}),
            mock.patch.object(deps, "_jwks_fetched_at", None),
            mock.patch.object(deps, "_jwks_last_attempt", time.monotonic()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": "me,other,synthetic-member-a,synthetic-member-b", "ANTHROPIC_API_KEY": "stub-not-a-real-key"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        ai_stub.install()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self._seed()
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
        self.h = {"Authorization": "Bearer " + access_token(self.key, "synthetic-member-a")}

    def _seed(self):
        db = self.Session()
        u = User(cognito_sub="synthetic-member-a", consent_given_at=None)
        db.add(u)
        db.commit()
        from datetime import datetime, timezone
        u.consent_given_at = datetime.now(timezone.utc)
        p = CareerProfile(user_id=u.id)
        db.add(p)
        db.commit()
        e = Experience(career_profile_id=p.id, title="Customer Service Lead", organization="Sample Company",
                       start_date="2022", end_date="2025",
                       description="Led a team of 6 agents handling customer escalations\nReduced average response time by 25% through a new triage process")
        db.add(e)
        db.commit()
        for name in ["Team leadership", "Zendesk", "Excel"]:
            db.add(Skill(career_profile_id=p.id, name=name, source="manual"))
        db.commit()
        db.close()

    def test_full_saved_job_journey_with_stub(self):
        made = self.client.post("/api/career/opportunities", headers=self.h,
                                json={"title": "Customer Service Lead", "employer": "Sample Employer",
                                      "job_url": "https://jobs.example-employer.com/postings/journey-1"})
        self.assertEqual(made.status_code, 200, made.text)
        oid = made.json()["id"]
        comp = self.client.post("/api/career/job-compare", headers=self.h, json={"job_description": POSTING, "opportunity_id": oid})
        self.assertEqual(comp.status_code, 200, comp.text)
        self.assertEqual(comp.json()["opportunity_id"], oid)
        build = self.client.post("/api/career/job-build-resume", headers=self.h,
                                 json={"job_description": POSTING, "name": "Synthetic Member A", "contact": "member.a@example.invalid | 555-0100",
                                       "scan_history_id": comp.json()["scan_history_id"], "confirmed_facts": [], "qa_history": []})
        self.assertEqual(build.status_code, 200, build.text)
        vid = build.json()["resume_version_id"]
        self.assertIsNotNone(vid)
        calls = ai_stub.STUB_CLIENT.messages.calls
        self.assertIn("submit_job_comparison", calls)
        self.assertIn("submit_term_plan", calls)
        self.assertIn("submit_tailored_resume", calls)
        body = build.json()
        self.assertTrue(body["resume_data"]["experience"][0]["bullets"], "the built résumé keeps the profile's bullets")
        self.assertEqual(body.get("claims_struck", []), [], "no claim was struck by the truthfulness checks")
        appr = self.client.put(f"/api/career/opportunities/{oid}/approval", headers=self.h, json={"approved_resume_version_id": vid})
        self.assertEqual(appr.status_code, 200, appr.text)
        doc = self.client.get(f"/api/career/opportunities/{oid}/approved-document", headers=self.h)
        self.assertEqual(doc.status_code, 200, doc.text)
        rec = self.client.post(f"/api/career/opportunities/{oid}/record-application", headers=self.h, json={"applied_on": "2026-11-11"})
        self.assertEqual(rec.status_code, 200, rec.text)
        app_id = rec.json()["application"]["id"]
        appdoc = self.client.get(f"/api/career/applications/{app_id}/approved-document", headers=self.h)
        self.assertTrue(appdoc.content == doc.content, "application keeps the stored approved document")
        lock = self.client.put(f"/api/career/applications/{app_id}", headers=self.h,
                               json={"job_title": "Customer Service Lead", "company": "Sample Employer", "applied_on": "2026-11-11",
                                     "status": "applied", "resume_version_id": None})
        self.assertEqual(lock.status_code, 409, lock.text)

    def test_stub_refuses_an_unknown_tool(self):
        with self.assertRaises(RuntimeError):
            ai_stub.STUB_CLIENT.messages.create(model="m", max_tokens=1, system="s", tools=[], tool_choice={"type": "tool", "name": "submit_unknown"}, messages=[{"role": "user", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
