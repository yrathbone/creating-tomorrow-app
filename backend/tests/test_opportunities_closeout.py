"""C-52 closeout regression tests (offline, SQLite, synthetic data). Covers the authorised fixes:
F01 recorded application résumé reference locked; F02 layout in the approval fingerprint; F03 URL identity and validation.

The harness (database, users, client, feature switch set inside the tests) is borrowed from tests/test_opportunities.py.
Concurrency behaviour needs PostgreSQL: here it is checked by recording the row locks the code requests (see LockSpy).
"""
import os
import unittest
from unittest import mock

from sqlalchemy.orm import Query

from career.opportunities import UNSUPPORTED_ADDRESS
from models import Application, CareerProfile, Opportunity, ResumeVersion
from tests import test_opportunities as base

GOOD = base.GOOD_URL
from career.routes import RECORDED_REFERENCE_LOCKED as LOCK_409
VERSION_409 = "A job application recorded from a saved job uses this résumé version"
APPROVAL_409 = "cannot change. The application keeps the résumé it was recorded with."


class LockSpy:
    """Records (entity, FOR UPDATE) requests made through SQLAlchemy queries during a block."""

    def __init__(self):
        self.locks = []
        self._orig = Query.with_for_update

    def __enter__(self):
        spy = self

        def recording(q, *a, **kw):
            try:
                entity = q.column_descriptions[0]["entity"].__name__
            except Exception:
                entity = "?"
            spy.locks.append(entity)
            return spy._orig(q, *a, **kw)

        self._patch = mock.patch.object(Query, "with_for_update", recording)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class CloseoutTests(unittest.TestCase):
    # borrow the harness from the base test class (methods are plain functions)
    setUp = base.OpportunityRoutes.setUp
    create = base.OpportunityRoutes.create
    count = base.OpportunityRoutes.count
    _body = base.OpportunityRoutes._body

    # ----------------------------------------------------------------- helpers
    def _db(self):
        return self.Session()

    def _second_version(self, data=None):
        db = self._db()
        v = ResumeVersion(career_profile_id=self.my_profile_id, resume_data=data or {"name": "Second Sample", "summary": "Second version."})
        db.add(v)
        db.commit()
        vid = v.id
        db.close()
        return vid

    def _link_approved_and_recorded(self, url=GOOD):
        made = self.create(job_url=url).json()
        ap = self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(ap.status_code, 200, ap.text)
        rec = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(rec.status_code, 200, rec.text)
        return made["id"], rec.json()["application"]["id"]

    def _app_body(self, **over):
        body = {"job_title": "Customer Service Lead", "company": "Sample Employer", "applied_on": "2026-11-09",
                "status": "applied", "notes": "edited", "resume_version_id": self.my_resume_id}
        body.update(over)
        return body

    def _opp_list(self):
        return self.client.get("/api/career/opportunities").json()

    def _approval_of(self, opp_id):
        return [x for x in self._opp_list() if x["id"] == opp_id][0]["approval"]

    # ----------------------------------------------------------------- F01: recorded reference locked
    def test_F01_recorded_application_refuses_a_different_resume_reference(self):
        opp_id, app_id = self._link_approved_and_recorded()
        other = self._second_version()
        r = self.client.put(f"/api/career/applications/{app_id}", json=self._app_body(resume_version_id=other))
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], LOCK_409)
        db = self._db()
        self.assertEqual(db.get(Application, app_id).resume_version_id, self.my_resume_id)
        self.assertEqual(db.get(Opportunity, opp_id).application_id, app_id)   # association kept
        db.close()

    def test_F01_recorded_application_refuses_clearing_the_reference(self):
        opp_id, app_id = self._link_approved_and_recorded()
        r = self.client.put(f"/api/career/applications/{app_id}", json=self._app_body(resume_version_id=None))
        self.assertEqual(r.status_code, 409, r.text)
        db = self._db()
        self.assertEqual(db.get(Application, app_id).resume_version_id, self.my_resume_id)
        db.close()

    def test_F01_recorded_application_still_accepts_unrelated_edits_and_same_reference(self):
        opp_id, app_id = self._link_approved_and_recorded()
        r = self.client.put(f"/api/career/applications/{app_id}", json=self._app_body(status="interview", notes="phone screen"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "interview")
        self.assertEqual(r.json()["resume_version_id"], self.my_resume_id)

    def test_F01_legacy_application_without_a_saved_job_is_unchanged(self):
        db = self._db()
        legacy = Application(career_profile_id=self.my_profile_id, job_title="Old role", status="applied", applied_on="2026-10-01", resume_version_id=self.my_resume_id)
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id
        db.close()
        other = self._second_version()
        r = self.client.put(f"/api/career/applications/{legacy_id}", json=self._app_body(job_title="Old role", resume_version_id=other))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["resume_version_id"], other)

    def test_F01_another_member_cannot_change_my_recorded_application(self):
        opp_id, app_id = self._link_approved_and_recorded()
        self.current_id = self.other_id
        r = self.client.put(f"/api/career/applications/{app_id}", json=self._app_body(resume_version_id=self.other_resume_id))
        self.assertEqual(r.status_code, 404, r.text)
        self.current_id = self.me_id
        db = self._db()
        self.assertEqual(db.get(Application, app_id).resume_version_id, self.my_resume_id)
        db.close()

    def test_F01_recorded_version_cannot_be_deleted_but_other_versions_can(self):
        self._link_approved_and_recorded()
        r = self.client.delete(f"/api/career/resume-versions/{self.my_resume_id}")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn(VERSION_409, r.json()["detail"])
        spare = self._second_version()
        self.assertEqual(self.client.delete(f"/api/career/resume-versions/{spare}").status_code, 200)

    def test_F01_recorded_version_cannot_be_changed_by_suggestion_undo(self):
        self._link_approved_and_recorded()
        r = self.client.post(f"/api/career/resume-versions/{self.my_resume_id}/suggestions/undo")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn(VERSION_409, r.json()["detail"])

    def test_F01_unrecorded_version_can_still_be_changed_by_suggestion_undo(self):
        spare = self._second_version()
        r = self.client.post(f"/api/career/resume-versions/{spare}/suggestions/undo")
        self.assertEqual(r.status_code, 200, r.text)

    def test_F01_deleting_the_application_is_allowed_and_leaves_the_saved_job_visible(self):
        opp_id, app_id = self._link_approved_and_recorded()
        self.assertEqual(self.client.delete(f"/api/career/applications/{app_id}").status_code, 200)
        item = [x for x in self._opp_list() if x["id"] == opp_id][0]
        self.assertEqual(item["state"], "saved")
        self.assertTrue(item["application_removed"])

    def test_F01_locks_are_requested_for_the_application_version_and_link_paths(self):
        opp_id, app_id = self._link_approved_and_recorded()
        with LockSpy() as spy:
            self.client.put(f"/api/career/applications/{app_id}", json=self._app_body(notes="x"))
        self.assertIn("Application", spy.locks)
        with LockSpy() as spy:
            self.client.delete(f"/api/career/resume-versions/{self._second_version()}")
        self.assertIn("ResumeVersion", spy.locks)
        with LockSpy() as spy:
            opp2 = self.create(job_url="https://jobs.example-employer.com/postings/lock").json()
            self.client.put(f"/api/career/opportunities/{opp2['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
            self.client.post(f"/api/career/opportunities/{opp2['id']}/record-application", json={})
        self.assertIn("Opportunity", spy.locks)
        self.assertIn("ResumeVersion", spy.locks)

    # ----------------------------------------------------------------- F02: layout in approval
    def test_F02_approval_is_current_then_invalid_after_layout_change_and_recording_is_refused(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(self._approval_of(made["id"])["status"], "current")
        self.assertEqual(self.client.put("/api/career/resume-layout", json={"layout": "modern"}).status_code, 200)
        self.assertEqual(self._approval_of(made["id"])["status"], "changed_since_approval")
        r = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("has changed since you approved it", r.json()["detail"])

    def test_F02_reapproval_after_layout_change_allows_recording(self):
        made = self.create().json()
        self.client.put("/api/career/resume-layout", json={"layout": "modern"})
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(self._approval_of(made["id"])["status"], "current")
        r = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={})
        self.assertEqual(r.status_code, 200, r.text)

    def test_F02_unrelated_profile_change_keeps_the_approval_current(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        db = self._db()
        p = db.get(CareerProfile, self.my_profile_id)
        p.contact_line = "Changed contact line, not part of the document body"
        db.commit()
        db.close()
        self.assertEqual(self._approval_of(made["id"])["status"], "current")

    def test_F02_content_change_invalidates_approval_and_recording_refuses_stale_approval(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        db = self._db()
        v = db.get(ResumeVersion, self.my_resume_id)
        v.resume_data = {**v.resume_data, "summary": "Edited after approval."}
        db.commit()
        db.close()
        self.assertEqual(self._approval_of(made["id"])["status"], "changed_since_approval")
        r = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={})
        self.assertEqual(r.status_code, 409, r.text)

    def test_F02_fingerprint_is_not_the_bare_content_hash(self):
        import hashlib, json
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        db = self._db()
        v = db.get(ResumeVersion, self.my_resume_id)
        bare = hashlib.sha256(json.dumps(v.resume_data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        stored = db.get(Opportunity, made["id"]).approved_resume_hash
        db.close()
        self.assertNotEqual(stored, bare)

    # ----------------------------------------------------------------- F03: URL identity and validation
    def test_F03_src_and_refid_are_kept_so_distinct_jobs_are_not_merged(self):
        a = self.create(job_url="https://jobs.example-employer.com/search?src=alpha&id=1")
        b = self.create(job_url="https://jobs.example-employer.com/search?src=beta&id=1")
        c = self.create(job_url="https://jobs.example-employer.com/search?refid=r1&id=2")
        d = self.create(job_url="https://jobs.example-employer.com/search?refid=r2&id=2")
        for r in (a, b, c, d):
            self.assertEqual(r.status_code, 200, r.text)

    def test_F03_marketing_parameters_are_still_ignored_for_duplicates(self):
        self.assertEqual(self.create(job_url=GOOD).status_code, 200)
        dup = self.create(job_url=GOOD + "?utm_source=mail&fbclid=abc&gclid=x&trk=1&trackingid=9")
        self.assertEqual(dup.status_code, 409, dup.text)

    def test_F03_fragment_ignored_for_duplicates_but_kept_in_the_stored_link(self):
        first = self.create(job_url=GOOD + "#apply").json()
        dup = self.create(job_url=GOOD + "#other")
        self.assertEqual(dup.status_code, 409, dup.text)
        self.assertEqual(first["job_url"], GOOD + "#apply")

    def test_F03_distinct_job_ids_and_paths_stay_distinct(self):
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/postings/10").status_code, 200)
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/postings/1").status_code, 200)
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/Postings/1").status_code, 200)
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/search?jk=111").status_code, 200)
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/search?jk=222").status_code, 200)

    def test_F03_query_order_alone_is_treated_as_the_same_link(self):
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/s?a=1&b=2").status_code, 200)
        self.assertEqual(self.create(job_url="https://jobs.example-employer.com/s?b=2&a=1").status_code, 409)

    def test_F03_unicode_host_gets_the_clear_message(self):
        r = self.create(job_url="https://jobs.exämple.com/x")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], UNSUPPORTED_ADDRESS)
        self.assertEqual(UNSUPPORTED_ADDRESS, "This web address isn’t supported yet. Please enter a standard HTTPS job link.")

    def test_F03_percent_encoded_host_is_refused_with_the_same_message(self):
        for url in ("https://jobs%2Eexample.com/x", "https://%6Aobs.example-employer.com/x"):
            with self.subTest(url=url):
                r = self.create(job_url=url)
                self.assertEqual(r.status_code, 400, r.text)
                self.assertEqual(r.json()["detail"], UNSUPPORTED_ADDRESS)

    def test_F03_punycode_host_is_accepted(self):
        self.assertEqual(self.create(job_url="https://xn--exmple-cua.com/x").status_code, 200)

    def test_F03_boundary_length_2000_accepted_2001_refused(self):
        prefix = "https://jobs.example-employer.com/p/"
        ok = prefix + "a" * (2000 - len(prefix))
        self.assertEqual(len(ok), 2000)
        self.assertEqual(self.create(job_url=ok).status_code, 200)
        too_long = prefix + "b" * (2001 - len(prefix))
        self.assertEqual(len(too_long), 2001)
        r = self.create(job_url=too_long)
        self.assertEqual(r.status_code, 400)

    def test_F03_existing_refusals_still_hold(self):
        for url in ("http://jobs.example-employer.com/1", "https://user:pw@jobs.example-employer.com/x",
                    "https://127.0.0.1/x", "https://jobs.example-employer.com:8443/x", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertEqual(self.create(job_url=url).status_code, 400)

    def test_F03_stored_link_is_the_submitted_text_not_a_rewritten_one(self):
        raw = "https://jobs.example-employer.com/postings/keep?src=alpha&utm_source=x#apply"
        made = self.create(job_url=raw).json()
        self.assertEqual(made["job_url"], raw)

    # ----------------------------------------------------------------- F05: saved-link context cannot be bypassed
    def _scan(self, result_data):
        from models import ScanHistory
        db = self._db()
        scan = ScanHistory(career_profile_id=self.my_profile_id, scan_type="job_comparison", job_title="Customer Service Lead",
                           summary_text="Summary.", result_data=result_data)
        db.add(scan)
        db.commit()
        sid = scan.id
        db.close()
        return sid

    def test_F05_application_from_a_comparison_started_from_a_saved_link_is_refused_on_the_tracker_route(self):
        made = self.create().json()
        scan_id = self._scan({"job_description": "Posting text for the test.", "opportunity_id": made["id"]})
        r = self.client.post("/api/career/applications", json={"job_title": "Customer Service Lead", "status": "applied", "scan_history_id": scan_id})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("saved job", r.json()["detail"])

    def test_F05_application_from_an_ordinary_comparison_is_unchanged(self):
        scan_id = self._scan({"job_description": "Posting text for the test."})
        r = self.client.post("/api/career/applications", json={"job_title": "Customer Service Lead", "status": "applied", "scan_history_id": scan_id})
        self.assertEqual(r.status_code, 200, r.text)

    def test_F05_comparison_cannot_be_linked_to_another_members_saved_job(self):
        other_link = self.create(job_url="https://jobs.example-employer.com/postings/other-member")
        self.current_id = self.other_id
        other_made = self.create(job_url="https://jobs.example-employer.com/postings/theirs").json()
        self.current_id = self.me_id
        r = self.client.post("/api/career/job-compare", json={"job_description": "A posting long enough to check for the test run.", "opportunity_id": other_made["id"]})
        self.assertIn(r.status_code, (404, 403), r.text)
        self.assertNotEqual(r.status_code, 200)

    # ----------------------------------------------------------------- F06: stale card cannot overwrite newer details
    def test_F06_details_save_from_an_outdated_card_is_refused_and_newer_details_stay(self):
        made = self.create().json()
        t0 = made["version"]
        first = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "From tab A", "if_version": t0})
        self.assertEqual(first.status_code, 200, first.text)
        t1 = first.json()["version"]
        self.assertNotEqual(t0, t1)
        stale = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "From stale tab B", "if_version": t0})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("Reload the page", stale.json()["detail"]["message"])
        db = self._db()
        self.assertEqual(db.get(Opportunity, made["id"]).notes, "From tab A")
        db.close()
        fresh = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "From tab B after reload", "if_version": t1})
        self.assertEqual(fresh.status_code, 200, fresh.text)

    def test_F06_an_approval_change_makes_an_outdated_card_stale(self):
        made = self.create().json()
        before = made["version"]
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        r = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "x", "if_version": before})
        self.assertEqual(r.status_code, 409, r.text)

    def test_F06_a_save_without_a_version_is_still_accepted_for_older_clients(self):
        made = self.create().json()
        r = self.client.put(f"/api/career/opportunities/{made['id']}", json={**self._body(), "notes": "no version sent"})
        self.assertEqual(r.status_code, 200, r.text)

    # ----------------------------------------------------------------- F02b: material rendering inputs
    def test_F02b_approval_is_still_current_after_an_ats_download_because_it_does_not_change_the_approved_rendering(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.assertEqual(self.client.get(f"/api/career/resume-versions/{self.my_resume_id}/download?ats_mode=true").status_code, 200)
        self.assertEqual(self._approval_of(made["id"])["status"], "current")

    def test_F02b_template_change_before_recording_blocks_recording_and_after_recording_the_record_is_unchanged(self):
        made = self.create().json()
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        self.client.put("/api/career/resume-layout", json={"layout": "traditional"})
        self.assertEqual(self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={}).status_code, 409)
        self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": self.my_resume_id})
        rec = self.client.post(f"/api/career/opportunities/{made['id']}/record-application", json={"applied_on": "2026-11-09"})
        self.assertEqual(rec.status_code, 200, rec.text)
        app_id = rec.json()["application"]["id"]
        self.client.put("/api/career/resume-layout", json={"layout": "modern"})
        db = self._db()
        self.assertEqual(db.get(Application, app_id).resume_version_id, self.my_resume_id)
        db.close()
        self.assertEqual(self.client.put(f"/api/career/applications/{app_id}", json=self._app_body(resume_version_id=None)).status_code, 409)


if __name__ == "__main__":
    unittest.main()
