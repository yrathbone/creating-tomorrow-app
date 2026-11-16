"""C-52 Step B: review gate for general résumés (tests first; written before the implementation, 2026-11-14).

Covers: review integrity (canonical hashes, no self-reference), member ownership on every decision / sign-off / download / approval,
stale-content and stale-facts rejection, unsupported and uncertain statements, member sign-off against the previewed content,
legacy-unverified versions, feature-switch behaviour (off / shadow / on), the owner-scoped DOCX download, and route separation.

Synthetic Accounts only. No paid AI call: build_general_resume is mocked with the output the model produced for Account B.
Run from the backend folder:  py -3.12 -m unittest tests.test_general_review_gate -v
"""
import copy
import io
import os
import unittest
from unittest import mock

from docx import Document

import abuse_guard
from career import review_gate as rg
from tests.test_ownership import OwnershipTestCase

B_ROLE = {"title": "Coordinator", "organization": "Fictional Organization Beta",
          "description": "Handled customer requests and kept records for a fictional office of eight. Improved the record-keeping checklist.",
          "start": "06/21", "end": "05/25"}
B_SKILLS = ["Customer support", "Record keeping", "Calendar planning", "Written communication"]
B_CONTENT = {
    "name": "SYNTHETIC Member B", "contact": "SYNTHETIC | synthetic.member.b@example.com",
    "headline": "Customer Support Coordinator | Records & Office Operations",
    "summary": ("Service-oriented coordinator with experience handling customer requests and maintaining records for a small office team. "
                "Skilled in record keeping, calendar planning, and written communication, with a track record of improving administrative processes. "
                "Certified in customer service and dependable in fast-paced, detail-driven environments."),
    "skills": ["Customer Support", "Record Keeping", "Calendar Planning", "Written Communication", "Process Improvement", "Office Administration"],
    "experience": [{"title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
                    "bullets": ["Handled customer requests and maintained records for a fictional office of eight.",
                                "Improved the record-keeping checklist, streamlining documentation practices."]}],
    "education": ["Fictional School B: Certificate, Customer Service"],
    "certifications": [], "skills_style": "grouped",
}
B_EDU = {"institution": "Fictional School B", "degree": "Certificate", "field_of_study": "Customer Service"}


class GateSwitch(unittest.TestCase):
    def test_default_is_off_and_invalid_values_are_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CT_GENERAL_RESUME_TRUTH_GATE", None)
            self.assertEqual(rg.gate_mode(), "off")
        for value in ("maybe", "ON ", "", "true"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": value}):
                self.assertEqual(rg.gate_mode(), "off")

    def test_shadow_and_on_are_recognised(self):
        for value in ("shadow", "on"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": value}):
                self.assertEqual(rg.gate_mode(), value)


class CanonicalHashing(unittest.TestCase):
    def test_hash_ignores_key_order_and_extra_spaces(self):
        a = {"name": "N  Name", "skills": ["x"], "contact": "c"}
        b = {"contact": "c", "skills": ["x"], "name": "N Name"}
        self.assertEqual(rg.content_hash(a), rg.content_hash(b))

    def test_review_keys_are_excluded_so_a_record_cannot_hash_itself(self):
        base = {"name": "N", "skills": []}
        with_review = dict(base, truth_review={"x": 1}, final_signoff={"y": 2})
        self.assertEqual(rg.content_hash(base), rg.content_hash(with_review))

    def test_any_content_change_changes_the_hash(self):
        self.assertNotEqual(rg.content_hash({"name": "N", "skills": []}), rg.content_hash({"name": "N", "skills": ["x"]}))


class GeneralBuildWithGate(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        from career.opportunities import router as opportunities_router
        from tests.test_ownership import SUB_A, SUB_B
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": f"{SUB_A},{SUB_B}"}),
            mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}),   # member review steps exist only while ON; builds pick their own mode
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.app.include_router(opportunities_router, prefix="/api/career")
        abuse_guard.IN_FLIGHT.reset()

    # ---- helpers -----------------------------------------------------------------------------------------------------------
    def _seed_b(self, who):
        self.onboard(who)
        res = self.call("POST", "/experiences", who, json={"title": B_ROLE["title"], "organization": B_ROLE["organization"],
                                                            "description": B_ROLE["description"], "start_date": B_ROLE["start"],
                                                            "end_date": B_ROLE["end"]})
        self.assertEqual(res.status_code, 200, res.text)
        for skill in B_SKILLS:
            self.assertEqual(self.call("POST", "/skills", who, json={"name": skill}).status_code, 200)
        self.assertEqual(self.call("POST", "/education", who, json=B_EDU).status_code, 200)

    def _build(self, who, mode):
        content = copy.deepcopy(B_CONTENT)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": content}):
            res = self.call("POST", "/build-general-resume", who, json={"name": "SYNTHETIC Member B",
                                                                       "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["resume_version_id"]

    def _review(self, who, version_id):
        return self.call("GET", f"/resume-versions/{version_id}/review", who)

    def _items(self, who, version_id):
        return self._review(who, version_id).json()["items"]

    def _decide(self, who, version_id, item_id, decision, acknowledge=False):
        return self.call("POST", f"/resume-versions/{version_id}/decisions", who,
                         json={"item_id": item_id, "decision": decision, "acknowledge": acknowledge})

    def _preview(self, who, version_id):
        return self.call("GET", f"/resume-versions/{version_id}/preview", who)

    def _signoff(self, who, version_id, finalized_hash):
        return self.call("POST", f"/resume-versions/{version_id}/signoff", who, json={"finalized_hash": finalized_hash})

    def _document(self, who, version_id):
        return self.call("GET", f"/resume-versions/{version_id}/document", who)

    def _signed_version(self, who, version_id):
        """Decide every UNCERTAIN item (keep, acknowledged), preview, then sign off. Returns the finalized hash."""
        for item in self._items(who, version_id):
            if item["classification"] == "UNCERTAIN" and item["decision"] is None:
                self.assertEqual(self._decide(who, version_id, item["id"], "keep", acknowledge=True).status_code, 200)
        preview = self._preview(who, version_id)
        self.assertEqual(preview.status_code, 200, preview.text)
        finalized_hash = preview.json()["finalized_hash"]
        self.assertEqual(self._signoff(who, version_id, finalized_hash).status_code, 200)
        return finalized_hash

    # ---- switch off: unchanged behaviour -----------------------------------------------------------------------------------
    def test_switch_off_saves_no_review_record_and_keeps_content_as_generated(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "off")
        self.assertEqual(self._review(self.a, vid).status_code, 409)           # no review exists: legacy-unverified
        doc = self._document(self.a, vid)
        self.assertEqual(doc.status_code, 409)                                  # never served without a sign-off

    # ---- shadow: records computed, nothing removed, nothing gated -----------------------------------------------------------
    def test_shadow_stores_findings_but_removes_nothing_and_does_not_gate(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "shadow")
        body = self._review(self.a, vid).json()
        classes = {i["classification"] for i in body["items"]}
        self.assertIn("UNSUPPORTED", classes)
        self.assertEqual(body["mode"], "shadow")
        self.assertIn("Office Administration", self.call("GET", f"/resume-versions", self.a).text)  # content untouched

    # ---- on: unsupported text removed before save; uncertain kept only as decisions -----------------------------------------
    def test_on_removes_unsupported_text_from_the_saved_draft(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        listed = self.call("GET", "/resume-versions", self.a).json()
        version = next(v for v in listed if v.get("id") == vid)
        draft = {k: x for k, x in version["resume_data"].items() if k not in ("truth_review", "member_review", "member_signoff")}
        text = str(draft)
        self.assertNotIn("Office Administration", text)
        self.assertNotIn("Certified in customer service", text)
        self.assertNotIn("track record", text)

    def test_on_lists_removed_statements_for_explanation_only(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        removed = self._review(self.a, vid).json().get("removed", [])
        self.assertTrue(any("Office Administration" in r["text"] for r in removed))

    def test_on_uncertain_items_need_an_explicit_decision(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        self.assertTrue(any(i["classification"] == "UNCERTAIN" and i["decision"] is None for i in self._items(self.a, vid)))

    # ---- decisions: integrity, ownership, contradictions ---------------------------------------------------------------------
    def test_unsupported_items_cannot_be_confirmed(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        unsupported = [i for i in self._items(self.a, vid) if i["classification"] == "UNSUPPORTED"]
        for item in unsupported:
            with self.subTest(item=item["text"][:30]):
                self.assertIn(self._decide(self.a, vid, item["id"], "keep", acknowledge=True).status_code, (409, 422))

    def test_uncertain_keep_requires_explicit_acknowledgement(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        item = next(i for i in self._items(self.a, vid) if i["classification"] == "UNCERTAIN")
        self.assertIn(self._decide(self.a, vid, item["id"], "keep", acknowledge=False).status_code, (400, 409, 422))
        self.assertEqual(self._decide(self.a, vid, item["id"], "keep", acknowledge=True).status_code, 200)

    def test_a_decision_for_an_unknown_item_is_refused(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        self.assertIn(self._decide(self.a, vid, "not-an-item", "keep", acknowledge=True).status_code, (400, 404, 409))

    def test_another_member_cannot_decide_on_my_version(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        item = next(i for i in self._items(self.a, vid) if i["classification"] == "UNCERTAIN")
        self.onboard(self.b)
        self.assertEqual(self._decide(self.b, vid, item["id"], "keep", acknowledge=True).status_code, 404)
        self.assertEqual(self._review(self.b, vid).status_code, 404)

    def test_a_decision_made_against_stale_facts_is_refused(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        item = next(i for i in self._items(self.a, vid) if i["classification"] == "UNCERTAIN")
        exp = self.call("GET", "/experiences", self.a).json()
        self.assertEqual(self.call("PUT", f"/experiences/{exp[0]['id']}", self.a, json={"title": B_ROLE["title"], "organization": B_ROLE["organization"],
                                                                                       "description": "Changed description.", "start_date": "07/21", "end_date": "05/25"}).status_code, 200)
        self.assertIn(self._decide(self.a, vid, item["id"], "keep", acknowledge=True).status_code, (409,))

    def test_a_client_supplied_review_record_is_not_accepted(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        res = self.call("POST", "/build-general-resume", self.a, json={"name": "N", "contact": "c@example.com",
                                                                       "truth_review": {"status": "ready"}, "final_signoff": {"finalized_hash": "x"}})
        self.assertNotIn(res.status_code, (500,))
        stored = self.call("GET", f"/resume-versions/{res.json().get('resume_version_id', vid)}/review", self.a)
        self.assertNotEqual(stored.json().get("status") if stored.status_code == 200 else None, "ready")

    # ---- sign-off: exact previewed content, no undecided items, ownership ----------------------------------------------------
    def test_signoff_is_refused_without_a_preview_of_the_same_content(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        for item in self._items(self.a, vid):
            if item["classification"] == "UNCERTAIN":
                self._decide(self.a, vid, item["id"], "keep", acknowledge=True)
        self.assertIn(self._signoff(self.a, vid, "f" * 64).status_code, (409, 422))

    def test_signoff_is_refused_while_an_uncertain_item_is_undecided(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        preview = self._preview(self.a, vid)
        self.assertIn(self._signoff(self.a, vid, preview.json()["finalized_hash"]).status_code, (409, 422))

    def test_signoff_succeeds_after_decisions_and_preview(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        self._signed_version(self.a, vid)
        self.assertEqual(self._document(self.a, vid).status_code, 200)

    def test_another_member_cannot_sign_or_download_my_version(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        finalized = self._signed_version(self.a, vid)
        self.onboard(self.b)
        self.assertEqual(self._document(self.b, vid).status_code, 404)
        self.assertEqual(self._signoff(self.b, vid, finalized).status_code, 404)

    # ---- document: stored, signed, owner-only ---------------------------------------------------------------------------------
    def test_document_is_the_signed_content_and_contains_no_removed_text(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        self._signed_version(self.a, vid)
        res = self._document(self.a, vid)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        text = "\n".join(p.text for p in Document(io.BytesIO(res.content)).paragraphs)
        self.assertIn("SYNTHETIC Member B", text)
        self.assertNotIn("Office Administration", text)
        self.assertNotIn("Customer Support Coordinator", text)

    def test_document_is_refused_when_facts_changed_after_sign_off(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        self._signed_version(self.a, vid)
        exp = self.call("GET", "/experiences", self.a).json()
        self.call("PUT", f"/experiences/{exp[0]['id']}", self.a, json={"title": B_ROLE["title"], "organization": B_ROLE["organization"],
                                                                      "description": "Changed.", "start_date": "07/21", "end_date": "05/25"})
        self.assertEqual(self._document(self.a, vid).status_code, 409)

    # ---- legacy and approval -------------------------------------------------------------------------------------------------
    def test_a_legacy_version_cannot_be_approved_when_the_gate_is_on(self):
        self._seed_b(self.a)
        legacy = self._build(self.a, "off")
        link = self.call("POST", "/opportunities", self.a, json={"title": "Analyst", "employer": "Sample Employer",
                                                                 "job_url": "https://jobs.example-employer.com/postings/1001",
                                                                 "location_text": "Chicago, IL", "work_arrangement": "hybrid", "employment_type": "full_time"})
        self.assertEqual(link.status_code, 200, link.text)
        oid = link.json()["id"]
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": legacy})
        self.assertEqual(res.status_code, 409, res.text)

    def test_an_approval_after_sign_off_freezes_the_signed_document(self):
        self._seed_b(self.a)
        vid = self._build(self.a, "on")
        self._signed_version(self.a, vid)
        link = self.call("POST", "/opportunities", self.a, json={"title": "Analyst", "employer": "Sample Employer",
                                                                 "job_url": "https://jobs.example-employer.com/postings/1001",
                                                                 "location_text": "Chicago, IL", "work_arrangement": "hybrid", "employment_type": "full_time"})
        oid = link.json()["id"]
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid})
            self.assertEqual(res.status_code, 200, res.text)
            doc = self.call("GET", f"/opportunities/{oid}/approved-document", self.a)
        self.assertEqual(doc.status_code, 200)
        text = "\n".join(p.text for p in Document(io.BytesIO(doc.content)).paragraphs)
        self.assertNotIn("Office Administration", text)

    # ---- public tools and route separation -----------------------------------------------------------------------------------
    def test_the_public_generate_route_still_renders_client_content(self):
        from main import app as main_app
        from fastapi.testclient import TestClient
        res = TestClient(main_app).post("/api/generate", json={"resume_data": {"name": "A", "contact": "c", "skills": [], "experience": [], "education": []}})
        self.assertEqual(res.status_code, 200)

    def test_member_frontend_download_no_longer_calls_api_generate(self):
        # Member downloads use stored versions only. /api/generate stays for the three anonymous public tools.
        root = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "career", "js")
        for name in ("generalResume.js", "jobMatch.js"):
            with open(os.path.join(root, name), encoding="utf8") as f:
                self.assertNotIn("/api/generate", f.read(), name)


if __name__ == "__main__":
    unittest.main()
