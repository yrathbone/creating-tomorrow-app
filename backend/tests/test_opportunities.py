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
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
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
        self._env = mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": "me,other,synthetic-member-a,synthetic-member-b"})
        self._env.start()
        self.addCleanup(self._env.stop)
        # no outbound network can happen in these tests
        for name in ("create_connection", "getaddrinfo"):
            p = mock.patch.object(socket, name, side_effect=_no_network)
            p.start()
            self.addCleanup(p.stop)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.engine = engine
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

    def test_numeric_hosts_in_any_notation_are_refused_on_save_and_update(self):
        made = self.create().json()
        for u in ("https://0x7f.0x0.0x0.0x1/", "https://192.168.0x1.0x1/", "https://0x7f.1/"):
            with self.subTest(url=u):
                self.assertEqual(self.create(job_url=u).status_code, 400)
                r = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "job_url": u})
                self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.client.get("/api/career/opportunities").json()[0]["job_url"], GOOD_URL)

    def test_record_application_refuses_impossible_dates(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        for bad in ("2026-02-31", "2026-13-01"):
            with self.subTest(applied_on=bad):
                r = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": bad})
                self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.count(Application), 0)
        ok = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-02-28"})
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_dismiss_filter_only_clears_my_own_dismissed_links(self):
        mine = self.create().json()
        self.client.put(f"/api/career/opportunities/{mine['id']}", json={**self._body(), "state": "dismissed"})
        self.current_id = self.other_id
        theirs = self.create(job_url="https://jobs.example-employer.com/postings/777").json()
        self.client.put(f"/api/career/opportunities/{theirs['id']}", json={**self._body(), "job_url": "https://jobs.example-employer.com/postings/777", "state": "dismissed"})
        self.assertEqual(self.client.delete("/api/career/opportunities?state=dismissed").json(), {"deleted": 1})
        self.current_id = self.me_id
        self.assertEqual(self.count(Opportunity), 1, "only the other member's own dismissed link was cleared; mine must survive")
        self.assertEqual([x["id"] for x in self.client.get("/api/career/opportunities").json()], [mine["id"]])
        self.assertEqual(self.client.delete("/api/career/opportunities?state=dismissed").json(), {"deleted": 1})
        self.assertEqual(self.client.get("/api/career/opportunities").json(), [])

    def test_update_and_record_lock_the_row_before_changing_it(self):
        """A PUT and a record-application on the same link must not interleave: both lock the row first."""
        from sqlalchemy.orm import Query
        made = self.create().json()
        locked = []
        real_lock = Query.with_for_update

        def spy(q, *a, **kw):
            if q.column_descriptions and q.column_descriptions[0].get("entity") is Opportunity:
                locked.append(True)
            return real_lock(q, *a, **kw)

        with mock.patch.object(Query, "with_for_update", spy):
            self.client.put(f"/api/career/opportunities/{made['id']}", json=self._body())
            self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(len(locked), 2, "PUT and record-application each lock the saved link")

    def test_approval_cannot_be_cleared_or_replaced_after_an_application_is_recorded(self):
        from models import ResumeVersion as RV
        db = self.Session()
        second = RV(career_profile_id=self.my_profile_id, resume_data={"name": "Sample Person", "summary": "A second version."})
        db.add(second)
        db.commit()
        second_id = second.id
        db.close()
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        rec = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(rec.status_code, 200, rec.text)
        app_id = rec.json()["application"]["id"]

        cleared = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": None})
        self.assertEqual(cleared.status_code, 409, cleared.text)
        replaced = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": second_id})
        self.assertEqual(replaced.status_code, 409, replaced.text)
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id}).status_code, 200)

        now = self.client.get("/api/career/opportunities").json()[0]
        self.assertEqual(now["approval"]["version_id"], self.my_resume_id)
        self.assertEqual(now["state"], "applied")
        db = self.Session()
        app = db.get(Application, app_id)
        self.assertEqual(app.resume_version_id, self.my_resume_id, "the application keeps the résumé it was recorded with")
        db.close()

    def test_unrelated_details_stay_editable_after_an_application_is_recorded(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"}).status_code, 200)
        r = self.client.put(f"/api/career/opportunities/{made['id']}", json={
            **self._body(), "notes": "Spoke to the hiring manager", "title": "Customer Service Lead II",
            "follow_up_on": "2026-11-20"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["notes"], "Spoke to the hiring manager")
        self.assertEqual(r.json()["title"], "Customer Service Lead II")
        self.assertEqual(r.json()["state"], "applied")

    def test_details_edit_never_changes_or_clears_the_approval(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        r = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "details only"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["approval"]["status"], "current")
        r2 = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "approved_resume_version_id": None})
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["approval"]["status"], "current")

    def test_recording_without_an_approved_resume_is_refused_and_approval_after_recording_is_refused(self):
        made = self.create().json()
        refused = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(self.count(Application), 0)
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"}).status_code, 200)
        r = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": None})
        self.assertEqual(r.status_code, 409, r.text)

    def test_approval_route_changes_only_the_approval_and_keeps_newer_details(self):
        """Stale-dashboard case: the list is loaded, the link is edited elsewhere, then approval is set from the old copy."""
        made = self.create().json()
        stale = {**made}                                       # the copy the dashboard holds
        edited = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "Newer note", "base_min": 81000, "base_max": 96000, "base_period": "annual", "title": "Customer Service Lead II"})
        self.assertEqual(edited.status_code, 200, edited.text)
        r = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(r.status_code, 200, r.text)
        now = self.client.get("/api/career/opportunities").json()[0]
        self.assertEqual(now["approval"]["version_id"], self.my_resume_id)
        self.assertEqual(now["notes"], "Newer note")
        self.assertEqual(now["title"], "Customer Service Lead II")
        self.assertEqual(now["base"], {"min": 81000, "max": 96000, "period": "annual"})
        self.assertNotEqual(now["title"], stale["title"])

    def test_approval_route_is_owned_refuses_others_versions_and_refuses_after_recording(self):
        made = self.create().json()
        self.current_id = self.other_id
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.other_resume_id}).status_code, 404)
        self.current_id = self.me_id
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.other_resume_id}).status_code, 400)
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"}).status_code, 200)
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": None}).status_code, 409)
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id}).status_code, 200)

    def test_cannot_approve_someone_elses_resume(self):
        made = self.create().json()
        r = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.other_resume_id})
        self.assertEqual(r.status_code, 400)

    # ---------------------------------------------------------------- approval per saved link and version
    def test_approval_is_for_one_version_and_reads_changed_after_an_edit(self):
        made = self.create().json()
        ok = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id}).json()
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
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
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
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
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
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
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
        self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "state": "saved"})
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
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

    # ---------------------------------------------------------------- review fixes (2026-11-10)
    def test_account_deletion_and_export_work_before_migration_0010(self):
        """Migration 0010 not applied: the opportunities table is missing. Existing routes must still work."""
        self.create()
        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE opportunities"))
        exported = self.client.get("/api/career/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.json().get("opportunities"), [])
        gone = self.client.post("/api/career/account/delete", json={"confirm": "DELETE"})
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(gone.json()["counts"]["opportunities"], 0)

    def test_trailing_dot_and_local_hosts_are_refused(self):
        bad = [
            "https://localhost./x", "https://LOCALHOST./x", "https://127.0.0.1./", "https://127.0.0.1/",
            "https://[::1]./", "https://jobs.example-employer.com./postings/1", "https://0177.0.0.1/",
            "https://0x7f.1/", "https://intranet.lan./x", "https://a..example.com/x", "https://example.com:8443/x",
        ]
        bad += [
            # alternate numeric IPv4 notations that browsers normalise to private or loopback addresses
            "https://0x7f.0x0.0x0.0x1/", "https://0x7f.0x0.0x0.0x1./", "https://0x7f.1/", "https://192.168.0x1.0x1/",
            "https://0x7F.0X0.0X0.0X1/", "https://0x0a000001/", "https://2130706433/", "https://0x7f000001/",
            "https://0177.0.0.01/", "https://10.0x0.0.1/", "https://0300.0250.0.1/", "https://127.1/", "https://0/",
            "https://0x/", "https://169.254.169.254/latest", "https://0xa9fea9fe/", "https://3232235777/",
        ]
        for u in bad:
            with self.subTest(url=u):
                r = self.create(job_url=u)
                self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.count(Opportunity), 0)

    def test_impossible_calendar_dates_are_refused(self):
        for field in ("last_verified_on", "follow_up_on"):
            for bad in ("2026-02-31", "2026-13-01", "2026-00-10", "2026-04-31"):
                with self.subTest(field=field, value=bad):
                    r = self.create(**{field: bad})
                    self.assertEqual(r.status_code, 400, r.text)
        ok = self.create(last_verified_on="2026-02-28", follow_up_on="2028-02-29")
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_export_includes_the_approval_fingerprint(self):
        created = self.create().json()
        put = self.client.put(f"/api/career/opportunities/{created['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(put.status_code, 200, put.text)
        row = self.client.get("/api/career/export").json()["opportunities"][0]
        self.assertEqual(row["approved_resume_version_id"], self.my_resume_id)
        self.assertRegex(row["approved_resume_hash"], r"^[0-9a-f]{64}$")

    def test_the_200_link_cap_is_checked_under_a_row_lock(self):
        """Count and insert must be serialised per member: the profile row is locked (FOR UPDATE) before the count.
        PostgreSQL honours the lock; SQLite ignores it. A real concurrent test on PostgreSQL is still required."""
        from sqlalchemy.orm import Query
        from sqlalchemy.dialects import postgresql
        lock_sql = str(self.Session().query(CareerProfile).filter_by(id=self.my_profile_id).with_for_update().statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE", lock_sql)
        events = []
        real_lock, real_count = Query.with_for_update, Query.count

        def lock_spy(q, *a, **kw):
            if q.column_descriptions and q.column_descriptions[0].get("entity") is CareerProfile:
                events.append("lock")
            return real_lock(q, *a, **kw)

        def count_spy(q, *a, **kw):
            if q.column_descriptions and q.column_descriptions[0].get("entity") is Opportunity:
                events.append("count")
            return real_count(q, *a, **kw)

        with mock.patch.object(Query, "with_for_update", lock_spy), mock.patch.object(Query, "count", count_spy):
            self.assertEqual(self.create().status_code, 200)
        self.assertEqual(events, ["lock", "count"], events)

    def test_cap_is_enforced_with_the_lock_in_place(self):
        self.assertEqual(self.create().status_code, 200)


if __name__ == "__main__":
    unittest.main()
