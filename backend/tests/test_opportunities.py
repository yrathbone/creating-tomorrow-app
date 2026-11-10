"""C-52 My Opportunities MVP-0: offline tests (in-memory SQLite, the login replaced, no network, no real member data).

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
The feature switch CT_OPPORTUNITIES_ENABLED is set only inside these tests and is off by default.
"""
import os
import socket
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth.dependencies import get_current_user
from career.opportunities import router as opportunities_router
from career.routes import router as career_router
from db import Base, get_db_session
from models import Application, CareerProfile, Opportunity, ResumeVersion, User

GOOD_URL = "https://jobs.example-employer.com/postings/1001"
SAFETY = "Creating Tomorrow does not endorse employers"


def _no_network(*args, **kwargs):
    raise AssertionError("network access attempted during an offline test")


class OpportunityRoutes(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1"})
        self._env.start()
        self.addCleanup(self._env.stop)
        # no outbound network can happen in these tests
        for name in ("create_connection", "getaddrinfo"):
            p = mock.patch.object(socket, name, side_effect=_no_network)
            p.start()
            self.addCleanup(p.stop)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        self.me = User(cognito_sub="me")
        self.other = User(cognito_sub="other")
        db.add_all([self.me, self.other])
        db.commit()
        self.my_profile = CareerProfile(user_id=self.me.id)
        self.other_profile = CareerProfile(user_id=self.other.id)
        db.add_all([self.my_profile, self.other_profile])
        db.commit()
        self.my_resume = ResumeVersion(career_profile_id=self.my_profile.id, resume_data={"name": "Sample Person", "summary": "Coordinates a team."})
        self.other_resume = ResumeVersion(career_profile_id=self.other_profile.id, resume_data={"name": "Other Sample"})
        db.add_all([self.my_resume, self.other_resume])
        db.commit()
        self.my_resume_id, self.other_resume_id = self.my_resume.id, self.other_resume.id
        self.me_id = self.me.id
        self.other_id = self.other.id
        self.my_profile_id = self.my_profile.id
        self.current_id = self.me_id
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

        def user():
            s = self.Session()
            u = s.get(User, self.current_id)
            s.close()
            return u

        app.dependency_overrides[get_db_session] = session
        app.dependency_overrides[get_current_user] = user
        self.client = TestClient(app, raise_server_exceptions=False)

    def create(self, **overrides):
        body = {"title": "Customer Service Lead", "employer": "Sample Employer", "job_url": GOOD_URL, "location_text": "Chicago, IL",
                "work_arrangement": "hybrid", "employment_type": "full_time"}
        body.update(overrides)
        return self.client.post("/api/career/opportunities", json=body)

    def count(self, model):
        db = self.Session()
        n = db.query(model).count()
        db.close()
        return n

    # ---------------------------------------------------------------- feature switch
    def test_switch_off_by_default_and_every_route_is_404(self):
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": ""}):
            self.assertEqual(self.client.get("/api/career/opportunities").status_code, 404)
            self.assertEqual(self.create().status_code, 404)
            self.assertEqual(self.client.post("/api/career/opportunities/1/record-application", json={}).status_code, 404)
        self.assertEqual(self.client.get("/api/career/opportunities").status_code, 200)

    # ---------------------------------------------------------------- create, list, safety text, source label
    def test_create_list_and_source_label(self):
        made = self.create()
        self.assertEqual(made.status_code, 200, made.text)
        body = made.json()
        self.assertEqual((body["state"], body["source"], body["job_url"]), ("saved", "Employer or other site (saved by you)", GOOD_URL))
        self.assertIn(SAFETY, body["safety_notice"])
        self.assertIsNone(body["application_id"])
        self.assertEqual([x["id"] for x in self.client.get("/api/career/opportunities").json()], [body["id"]])
        li = self.create(job_url="https://www.linkedin.com/jobs/view/2", title="Analyst").json()
        self.assertEqual(li["source"], "LinkedIn (saved by you)")
        evil = self.create(job_url="https://linkedin.com.evil.com/x", title="Other").json()
        self.assertEqual(evil["source"], "Employer or other site (saved by you)")

    def test_hostile_text_is_stored_and_returned_as_plain_data(self):
        made = self.create(title="<script>alert(1)</script>", employer="Ben & Jerry's \"quoted\"", notes="line one\nline two")
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["title"], "<script>alert(1)</script>")
        self.assertEqual(made.json()["notes"], "line one\nline two")
        self.assertEqual(made.headers["content-type"].split(";")[0], "application/json")

    # ---------------------------------------------------------------- URL rules
    def test_url_rules_refuse_everything_that_is_not_a_plain_public_https_link(self):
        bad = [
            "http://jobs.example-employer.com/1", "javascript:alert(1)", "data:text/html,hi", "file:///C:/x", "ftp://jobs.example-employer.com/x",
            "//jobs.example-employer.com/x", "https://user:secret@jobs.example-employer.com/x", "https://user@jobs.example-employer.com/x",
            "https://localhost/x", "https://127.0.0.1/x", "https://[::1]/x", "https://10.0.0.5/x", "https://intranet.local/x",
            "https://intranet/x", "https://jobs.example-employer.com:8443/x", "https://jobs example.test/x", "https://jobs.example-employer.com/a\tb",
            "https://jobs.example-employer.com/" + "a" * 2000, "", "   ", "https://jobs.exämple.com/x", "https://service.internal/x",
        ]
        for url in bad:
            with self.subTest(url=url[:60]):
                r = self.create(job_url=url)
                self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.count(Opportunity), 0)

    def test_duplicate_detected_across_tracking_parameters_and_trailing_slash(self):
        first = self.create().json()
        r = self.create(job_url=GOOD_URL + "/?utm_source=mail&fbclid=abc")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["existing_id"], first["id"])
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/postings/1002").status_code, 200)

    def test_cap_of_200_saved_links(self):
        db = self.Session()
        db.add_all([Opportunity(career_profile_id=self.my_profile_id, title=f"t{i}", job_url=f"https://e{i}.example-employer.com/x",
                                dedupe_key=f"k{i}", state="saved") for i in range(200)])
        db.commit()
        db.close()
        r = self.create(job_url="https://extra.example-employer.com/x")
        self.assertEqual(r.status_code, 409)
        self.assertIn("200", r.json()["detail"])

    # ---------------------------------------------------------------- pay rules
    def test_pay_rules(self):
        ok = self.create(base_min=52000, base_max=58000, base_period="annual", pay_note="Bonus up to 10% (not base)").json()
        self.assertEqual(ok["base"], {"min": 52000, "max": 58000, "period": "annual"})
        self.assertEqual(ok["pay_note"], "Bonus up to 10% (not base)")
        cases = [dict(base_min=60000, base_max=50000, base_period="annual"), dict(base_min=52000),
                 dict(base_period="annual"), dict(base_min=-1, base_period="annual"), dict(base_min=10_000_001, base_period="annual"),
                 dict(base_min=True, base_period="annual")]
        for n, bad in enumerate(cases):
            with self.subTest(case=n):
                self.assertIn(self.create(job_url=f"https://jobs.example-employer.com/pay/{n}", **bad).status_code, (400, 422))
        no_base = self.create(job_url="https://jobs.example-employer.com/postings/9", pay_note="OTE $100k").json()
        self.assertIsNone(no_base["base"])   # OTE text never becomes base pay

    def test_enums_and_states(self):
        self.assertEqual(self.create(work_arrangement="telecommute").status_code, 400)
        made = self.create().json()
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "state": "applied"}).status_code, 400)
        dismissed = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "state": "dismissed", "dismiss_reason": "pay_too_low"}).json()
        self.assertEqual((dismissed["state"], dismissed["dismiss_reason"]), ("dismissed", "pay_too_low"))

    def _body(self):
        return {"title": "Customer Service Lead", "employer": "Sample Employer", "job_url": GOOD_URL, "location_text": "Chicago, IL",
                "work_arrangement": "hybrid", "employment_type": "full_time"}

    # ---------------------------------------------------------------- tenant isolation
    def test_another_member_cannot_see_change_or_delete_my_links(self):
        mine = self.create().json()
        self.current_id = self.other_id
        self.assertEqual(self.client.get("/api/career/opportunities").json(), [])
        self.assertEqual(self.client.put(f"/api/career/opportunities/{mine['id']}", json=self._body()).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/career/opportunities/{mine['id']}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/career/opportunities/{mine['id']}/record-application", json={}).status_code, 404)
        self.current_id = self.me_id
        self.assertEqual(len(self.client.get("/api/career/opportunities").json()), 1)

    def test_cannot_approve_someone_elses_resume(self):
        made = self.create().json()
        r = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "approved_resume_version_id": self.other_resume_id})
        self.assertEqual(r.status_code, 400)

    # ---------------------------------------------------------------- approval per saved link and version
    def test_approval_is_for_one_version_and_reads_changed_after_an_edit(self):
        made = self.create().json()
        ok = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "approved_resume_version_id": self.my_resume_id}).json()
        self.assertEqual(ok["approval"], {"version_id": self.my_resume_id, "status": "current"})
        db = self.Session()
        v = db.get(ResumeVersion, self.my_resume_id)
        v.resume_data = {**v.resume_data, "summary": "Changed after approval."}
        db.commit()
        db.close()
        listed = self.client.get("/api/career/opportunities").json()[0]
        self.assertEqual(listed["approval"]["status"], "changed_since_approval")

    # ---------------------------------------------------------------- record application: retry-safe and atomic
    def test_record_application_links_both_rows_and_retry_creates_nothing_new(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "approved_resume_version_id": self.my_resume_id})
        first = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["already_recorded"])
        self.assertEqual(first.json()["opportunity"]["state"], "applied")
        self.assertEqual(first.json()["application"]["resume_version_id"], self.my_resume_id)
        second = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["already_recorded"])
        self.assertEqual(self.count(Application), 1)

    def test_failure_during_recording_leaves_no_application_and_no_link(self):
        made = self.create().json()
        from sqlalchemy.orm import Session
        real_commit = Session.commit
        calls = {"n": 0}

        def failing_commit(session, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated failure before the record was complete")
            return real_commit(session, *a, **k)

        with mock.patch.object(Session, "commit", failing_commit):
            r = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.count(Application), 0)
        listed = self.client.get("/api/career/opportunities").json()[0]
        self.assertEqual((listed["state"], listed["application_id"]), ("saved", None))

    def test_deleted_application_reads_as_saved_and_can_be_recorded_again(self):
        made = self.create().json()
        rec = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"}).json()
        app_id = rec["application"]["id"]
        self.assertEqual(self.client.delete(f"/api/career/applications/{app_id}").status_code, 200)
        listed = self.client.get("/api/career/opportunities").json()[0]
        self.assertEqual((listed["state"], listed["application_removed"], listed["application_id"]), ("saved", True, None))
        again = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-10"})
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["already_recorded"])
        self.assertEqual(self.count(Application), 1)

    def test_dismissed_must_be_restored_before_recording_and_stale_approval_blocks_recording(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "state": "dismissed"})
        self.assertEqual(self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={}).status_code, 409)
        self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "state": "saved", "approved_resume_version_id": self.my_resume_id})
        db = self.Session()
        db.get(ResumeVersion, self.my_resume_id).resume_data = {"changed": True}
        db.commit()
        db.close()
        self.assertEqual(self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={}).status_code, 409)
        self.assertEqual(self.count(Application), 0)

    # ---------------------------------------------------------------- export, delete, no network
    def test_export_includes_saved_links_and_account_deletion_removes_them(self):
        self.create()
        exported = self.client.get("/api/career/export").json()
        self.assertEqual(len(exported["opportunities"]), 1)
        self.assertNotIn("source", exported["opportunities"][0])   # plain stored fields only
        gone = self.client.post("/api/career/account/delete", json={"confirm": "DELETE"})
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(self.count(Opportunity), 0)

    def test_clear_dismissed_only_removes_dismissed(self):
        keep = self.create().json()
        drop = self.create(job_url="https://jobs.example-employer.com/postings/5").json()
        self.client.put(f"/api/career/opportunities/{drop['id']}", json={**self._body(), "job_url": "https://jobs.example-employer.com/postings/5", "state": "dismissed"})
        r = self.client.delete("/api/career/opportunities?state=dismissed")
        self.assertEqual(r.json(), {"deleted": 1})
        self.assertEqual([x["id"] for x in self.client.get("/api/career/opportunities").json()], [keep["id"]])


if __name__ == "__main__":
    unittest.main()
