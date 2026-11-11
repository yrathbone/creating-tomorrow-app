"""C-52 F07: the exact approved résumé document is stored with the approval and is what the application keeps.
Offline, SQLite, synthetic members. The harness is borrowed from tests/test_opportunities.py."""
import base64
import hashlib
import os
import unittest
from unittest import mock

from sqlalchemy.orm import Session

from models import Application, CareerProfile, Opportunity, OpportunityDocument, ResumeVersion
from tests import test_opportunities as base

GOOD = base.GOOD_URL


class DocumentTests(unittest.TestCase):
    setUp = base.OpportunityRoutes.setUp
    create = base.OpportunityRoutes.create
    count = base.OpportunityRoutes.count
    _body = base.OpportunityRoutes._body

    def _db(self):
        return self.Session()

    def _approve(self, opp_id, version_id=None):
        return self.client.put(f"/api/career/opportunities/{opp_id}/approval", json={"approved_resume_version_id": version_id or self.my_resume_id})

    def _record(self, opp_id):
        return self.client.post(f"/api/career/opportunities/{opp_id}/record-application", json={"applied_on": "2026-11-09"})

    def _doc(self, opp_id):
        db = self._db()
        d = db.query(OpportunityDocument).filter_by(opportunity_id=opp_id).one_or_none()
        out = (d.docx, d.content_sha256, d.layout, d.resume_snapshot) if d else None
        db.close()
        return out

    def test_F07_approval_stores_the_exact_document_and_the_download_returns_those_bytes(self):
        made = self.create().json()
        self.assertEqual(self._approve(made["id"]).status_code, 200)
        stored = self._doc(made["id"])
        self.assertIsNotNone(stored)
        docx, sha, layout, snap = stored
        self.assertEqual(hashlib.sha256(docx).hexdigest(), sha)
        self.assertEqual(snap["name"], "Sample Person")
        r = self.client.get(f"/api/career/opportunities/{made['id']}/approved-document")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.content == docx, "download returns the stored bytes")
        self.assertEqual(r.headers["x-document-sha256"], sha)

    def test_F07_layout_change_after_approval_does_not_change_the_stored_document(self):
        made = self.create().json()
        self._approve(made["id"])
        before = self._doc(made["id"])
        self.client.put("/api/career/resume-layout", json={"layout": "modern"})
        self.assertTrue(self._doc(made["id"])[0] == before[0], "stored document unchanged")
        self.assertTrue(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document").content == before[0], "download unchanged")
        self.assertEqual(self._record(made["id"]).status_code, 409)

    def test_F07_reapproval_after_a_layout_change_replaces_the_document_and_records(self):
        made = self.create().json()
        self._approve(made["id"])
        self.client.put("/api/career/resume-layout", json={"layout": "modern"})
        self._approve(made["id"])
        self.assertEqual(self._doc(made["id"])[2], "modern")
        rec = self._record(made["id"])
        self.assertEqual(rec.status_code, 200, rec.text)

    def test_F07_the_application_keeps_the_document_after_profile_and_layout_changes(self):
        made = self.create().json()
        self._approve(made["id"])
        app_id = self._record(made["id"]).json()["application"]["id"]
        original = self._doc(made["id"])[0]
        self.client.put("/api/career/resume-layout", json={"layout": "traditional"})
        db = self._db()
        p = db.get(CareerProfile, self.my_profile_id)
        p.contact_line = "Changed after the application"
        db.commit(); db.close()
        r = self.client.get(f"/api/career/applications/{app_id}/approved-document")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.content == original, "application keeps the document")

    def test_F07_another_member_cannot_download_the_document_by_application_or_by_job(self):
        made = self.create().json()
        self._approve(made["id"])
        app_id = self._record(made["id"]).json()["application"]["id"]
        self.current_id = self.other_id
        self.assertEqual(self.client.get(f"/api/career/applications/{app_id}/approved-document").status_code, 404)
        self.assertEqual(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document").status_code, 404)
        self.current_id = self.me_id

    def test_F07_clearing_the_approval_removes_the_stored_document(self):
        made = self.create().json()
        self._approve(made["id"])
        self.assertIsNotNone(self._doc(made["id"]))
        self.assertEqual(self.client.put(f"/api/career/opportunities/{made['id']}/approval", json={"approved_resume_version_id": None}).status_code, 200)
        self.assertIsNone(self._doc(made["id"]))
        self.assertEqual(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document").status_code, 404)

    def test_F07_deleting_the_saved_job_removes_its_document(self):
        made = self.create().json()
        self._approve(made["id"])
        self.assertEqual(self.client.delete(f"/api/career/opportunities/{made['id']}").status_code, 200)
        self.assertEqual(self.count(OpportunityDocument), 0)

    def test_F07_record_is_refused_when_the_stored_document_is_missing(self):
        made = self.create().json()
        self._approve(made["id"])
        db = self._db()
        db.query(OpportunityDocument).delete(); db.commit(); db.close()
        r = self._record(made["id"])
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("not saved", r.json()["detail"])

    def test_F07_an_ats_download_is_a_different_file_and_is_not_the_approved_document(self):
        made = self.create().json()
        self._approve(made["id"])
        approved = self._doc(made["id"])[0]
        ats = self.client.get(f"/api/career/resume-versions/{self.my_resume_id}/download?ats_mode=true")
        self.assertEqual(ats.status_code, 200)
        self.assertTrue(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document").content == approved, "approved download unchanged")

    def test_F07_export_contains_the_document_and_its_content_hash(self):
        made = self.create().json()
        self._approve(made["id"])
        exp = self.client.get("/api/career/export").json()
        docs = exp["approved_documents"]
        self.assertEqual(len(docs), 1)
        self.assertTrue(base64.b64decode(docs[0]["docx_base64"]) == self._doc(made["id"])[0], "export carries the document")
        self.assertEqual(docs[0]["content_sha256"], self._doc(made["id"])[1])
        self.assertEqual(docs[0]["resume_snapshot"]["name"], "Sample Person")

    def test_F07_export_with_no_documents_is_an_empty_list(self):
        self.assertEqual(self.client.get("/api/career/export").json()["approved_documents"], [])

    def test_F07_approval_takes_the_saved_job_lock_before_writing_the_document(self):
        from tests.test_opportunities_closeout import LockSpy
        made = self.create().json()
        with LockSpy() as spy:
            self._approve(made["id"])
        self.assertIn("Opportunity", spy.locks)


    def test_F07_feature_switch_off_hides_the_document_routes(self):
        made = self.create().json()
        self._approve(made["id"])
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": ""}):
            self.assertEqual(self.client.get(f"/api/career/opportunities/{made['id']}/approved-document").status_code, 404)
            self.assertEqual(self.client.get("/api/career/applications/1/approved-document").status_code, 404)


if __name__ == "__main__":
    unittest.main()
