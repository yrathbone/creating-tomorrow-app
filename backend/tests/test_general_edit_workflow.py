"""C-52 Edit decision and stored-version downloads (member workflow, switch ON unless stated).

Edit: the member's own wording of an UNCERTAIN statement is revalidated on the server against the saved facts. An UNSUPPORTED wording
is refused. An edited statement has a new identity, so no earlier Keep carries over to it, and any edit clears the sign-off.

Downloads: the general and the job-targeted résumés are downloaded from their stored versions, owner-scoped. The general signed download
exists only while the switch is ON.

Run from the backend folder:  py -3.12 -m unittest tests.test_general_edit_workflow -v
"""
import copy
import os
import unittest
from unittest import mock

import abuse_guard
from career import review_gate as rg
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B

CONTENT = {
    "name": "SYNTHETIC Member B", "contact": "SYNTHETIC | synthetic.member.b@example.com",
    "headline": "Records & Office Operations",
    "summary": ("Handled customer requests and kept records for a fictional office of eight. "
                "Service-oriented coordinator with experience handling customer requests and maintaining records for a small office team."),
    "skills": ["Record Keeping"],
    "experience": [{"title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
                    "bullets": ["Improved the record-keeping checklist."]}],
    "education": ["Fictional School B: Certificate, Customer Service"], "certifications": [], "skills_style": "grouped",
}
PLAUSIBLE = "Service-oriented coordinator with experience handling customer requests and maintaining records for a small office team."


class EditWorkflow(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        from career.opportunities import router as opportunities_router
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
            mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": f"{SUB_A},{SUB_B}"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.app.include_router(opportunities_router, prefix="/api/career")
        abuse_guard.IN_FLIGHT.reset()
        self.onboard(self.a)
        self.assertEqual(self.call("POST", "/experiences", self.a, json={
            "title": "Coordinator", "organization": "Fictional Organization Beta",
            "description": "Handled customer requests and kept records for a fictional office of eight. Improved the record-keeping checklist.",
            "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        self.assertEqual(self.call("POST", "/skills", self.a, json={"name": "Record keeping"}).status_code, 200)
        self.assertEqual(self.call("POST", "/education", self.a, json={"institution": "Fictional School B", "degree": "Certificate",
                                                                        "field_of_study": "Customer Service"}).status_code, 200)

    def _build(self, content=None, mode="on"):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": copy.deepcopy(content or CONTENT)}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B",
                                                                           "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _review(self, vid, who=None):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            return self.call("GET", f"/resume-versions/{vid}/review", who or self.a)

    def _item(self, vid, where):
        return next(i for i in self._review(vid).json()["items"] if i["where"] == where)

    def _decide(self, vid, item_id, decision, acknowledge=False, text=None, who=None):
        body = {"item_id": item_id, "decision": decision, "acknowledge": acknowledge}
        if text is not None:
            body["text"] = text
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            return self.call("POST", f"/resume-versions/{vid}/decisions", who or self.a, json=body)

    def _stored(self, vid):
        listed = self.call("GET", "/resume-versions", self.a).json()
        return next(v for v in listed if v.get("id") == vid)["resume_data"]

    def _sign_everything(self, vid):
        for item in self._review(vid).json()["items"]:
            if item["classification"] == "UNCERTAIN" and item["decision"] is None:
                self.assertEqual(self._decide(vid, item["id"], "keep", acknowledge=True).status_code, 200)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json()["can_sign_off"])
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview.json()["finalized_hash"]}).status_code, 200)
        return preview.json()

    # ---- Edit: accepted when the wording is supported --------------------------------------------------------------------
    def test_an_uncertain_headline_can_be_edited_to_a_supported_wording(self):
        vid = self._build()["resume_version_id"]
        head = self._item(vid, "headline[0]")
        res = self._decide(vid, head["id"], "edit", text="Coordinator")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self._stored(vid)["headline"], "Coordinator")
        self.assertFalse(any(i["where"] == "headline[0]" for i in self._review(vid).json()["items"]))   # now SUPPORTED: no item

    # ---- Edit: refused when the wording is not supported ---------------------------------------------------------------
    def test_an_edit_to_unsupported_wording_is_refused_and_nothing_is_stored(self):
        vid = self._build()["resume_version_id"]
        before = self._stored(vid)
        head = self._item(vid, "headline[0]")
        res = self._decide(vid, head["id"], "edit", text="Customer Support Coordinator")
        self.assertEqual(res.status_code, 409, res.text)
        self.assertEqual(self._stored(vid), before)

    def test_an_edit_to_a_certification_never_held_is_refused(self):
        vid = self._build()["resume_version_id"]
        summary = self._item(vid, "summary[1]")
        res = self._decide(vid, summary["id"], "edit", text="Certified in customer service.")
        self.assertEqual(res.status_code, 409, res.text)

    # ---- Edit: an edited statement never inherits an earlier Keep -------------------------------------------------------
    def test_an_edited_statement_has_a_new_identity_and_needs_its_own_decision(self):
        vid = self._build()["resume_version_id"]
        summary = self._item(vid, "summary[1]")
        self.assertEqual(self._decide(vid, summary["id"], "keep", acknowledge=True).status_code, 200)
        new_wording = "Service-oriented coordinator who handled customer requests and kept records for a small office team."
        self.assertEqual(self._decide(vid, summary["id"], "edit", text=new_wording).status_code, 200)
        items = [i for i in self._review(vid).json()["items"] if i["where"] == "summary[1]"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], new_wording)
        self.assertIsNone(items[0]["decision"])          # the earlier Keep does not carry over
        self.assertEqual(self._review(vid).json()["status"], "needs_review")

    def test_other_statements_keep_their_decisions_after_an_edit(self):
        vid = self._build()["resume_version_id"]
        summary = self._item(vid, "summary[1]")
        head = self._item(vid, "headline[0]")
        self.assertEqual(self._decide(vid, head["id"], "keep", acknowledge=True).status_code, 200)
        self.assertEqual(self._decide(vid, summary["id"], "edit", text="Coordinator and record keeper for a small office team.").status_code, 200)
        kept = next(i for i in self._review(vid).json()["items"] if i["where"] == "headline[0]")
        self.assertEqual(kept["decision"], "keep")

    # ---- Edit: any edit clears the sign-off ------------------------------------------------------------------------------
    def test_an_edit_after_sign_off_removes_the_sign_off_and_blocks_the_download(self):
        vid = self._build()["resume_version_id"]
        self._sign_everything(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 200)
        target = self._item(vid, "summary[1]")
        self.assertEqual(self._decide(vid, target["id"], "edit", text="Coordinator and record keeper for a small office team.").status_code, 200)
        self.assertNotIn("final_signoff", self._stored(vid))
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)

    def test_the_edited_wording_is_what_the_preview_and_sign_off_show(self):
        vid = self._build()["resume_version_id"]
        self._decide(vid, self._item(vid, "headline[0]")["id"], "edit", text="Coordinator")
        self._sign_everything(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            doc = self.call("GET", f"/resume-versions/{vid}/document", self.a)
        self.assertEqual(doc.status_code, 200)
        text = rg.docx_text(doc.content)
        self.assertNotIn("Records & Office Operations", text)
        self.assertIn("Coordinator", text)

    # ---- Edit: validation and isolation -----------------------------------------------------------------------------------
    def test_edit_requires_text_that_is_new_and_within_the_limit(self):
        vid = self._build()["resume_version_id"]
        head = self._item(vid, "headline[0]")
        self.assertEqual(self._decide(vid, head["id"], "edit", text="").status_code, 400)
        self.assertEqual(self._decide(vid, head["id"], "edit", text="Records & Office Operations").status_code, 400)
        self.assertEqual(self._decide(vid, head["id"], "edit", text="x" * 301).status_code, 400)
        self.assertEqual(self._decide(vid, head["id"], "edit", text="Coordinator | Records").status_code, 400)

    def test_an_edit_on_an_unknown_statement_is_refused(self):
        vid = self._build()["resume_version_id"]
        self.assertEqual(self._decide(vid, "not-a-statement", "edit", text="Coordinator").status_code, 404)

    def test_another_member_cannot_edit_my_statement(self):
        vid = self._build()["resume_version_id"]
        head = self._item(vid, "headline[0]")
        self.onboard(self.b)
        self.assertEqual(self._decide(vid, head["id"], "edit", text="Coordinator", who=self.b).status_code, 404)
        self.assertEqual(self._stored(vid)["headline"], CONTENT["headline"])

    def test_edit_is_not_available_while_the_switch_is_off_or_shadow(self):
        vid = self._build(mode="shadow")["resume_version_id"]
        head = self._item(vid, "headline[0]")
        for mode in ("shadow", "off"):
            with self.subTest(mode=mode), mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}):
                res = self.call("POST", f"/resume-versions/{vid}/decisions", self.a,
                                json={"item_id": head["id"], "decision": "edit", "acknowledge": False, "text": "Coordinator"})
                self.assertEqual(res.status_code, 409, res.text)

    def test_the_build_response_says_which_switch_state_produced_it(self):
        self.assertEqual(self._build(mode="on")["truth_gate"], "on")
        self.assertEqual(self._build(mode="off")["truth_gate"], "off")


    def test_the_review_lists_what_the_saved_information_supports_with_its_source(self):
        vid = self._build()["resume_version_id"]
        body = self._review(vid).json()
        self.assertTrue(body["supported"], "an exact saved sentence should be listed as supported")
        self.assertTrue(all(row.get("source") for row in body["supported"]))
        self.assertIn("derived", body)

    def test_each_edit_is_recorded_with_the_original_and_the_new_wording(self):
        vid = self._build()["resume_version_id"]
        head = self._item(vid, "headline[0]")
        self.assertEqual(self._decide(vid, head["id"], "edit", text="Coordinator").status_code, 200)
        edits = self._review(vid).json()["edits"]
        self.assertEqual(len(edits), 1)
        self.assertEqual((edits[0]["old_text"], edits[0]["new_text"], edits[0]["where"]), (CONTENT["headline"], "Coordinator", "headline[0]"))


class StoredVersionDownloads(OwnershipTestCase):
    """The general and job-targeted downloads read the stored version only; another member gets 404."""

    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
            mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()
        self.onboard(self.a)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "off"}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": copy.deepcopy(CONTENT)}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B",
                                                                           "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        self.vid = res.json()["resume_version_id"]

    def test_the_stored_version_downloads_for_its_owner_as_docx(self):
        res = self.call("GET", f"/resume-versions/{self.vid}/download?ats_mode=false&template=classic", self.a)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.content.startswith(b"PK"))

    def test_another_member_gets_404_for_the_stored_download(self):
        self.onboard(self.b)
        self.assertEqual(self.call("GET", f"/resume-versions/{self.vid}/download", self.b).status_code, 404)


if __name__ == "__main__":
    unittest.main()
