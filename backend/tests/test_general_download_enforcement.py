"""C-52 round 6: the legacy stored-version download cannot bypass the general résumé review.

Rules tested (server side, by version kind; ownership and authentication are checked first and always):
- general_review (built with the truth check): with the switch ON only the signed document is served, with the same checks as /document.
  Without a current sign-off, after an edit, or after a saved fact changed, the legacy endpoint refuses. With the switch OFF or SHADOW
  nothing is enforced (unchanged behaviour).
- general_legacy (saved before the truth check): with the switch ON the legacy endpoint refuses it; with OFF or SHADOW it is served as
  before (historical access).
- job (job-targeted, its own stored checks): served as before in every mode; its review is the separate planned integration.
- The three anonymous public tools are not affected (the /api/generate route still needs no sign-in).

Run from the backend folder:  py -3.12 -m unittest tests.test_general_download_enforcement -v
"""
import copy
import os
import re
import unittest
from unittest import mock

import abuse_guard
from models import ResumeVersion
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
LEGACY_REFUSAL = "saved before the truth check"


class DownloadEnforcement(OwnershipTestCase):
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
        self.assertEqual(self.call("POST", "/experiences", self.a, json={
            "title": "Coordinator", "organization": "Fictional Organization Beta",
            "description": "Handled customer requests and kept records for a fictional office of eight. Improved the record-keeping checklist.",
            "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        self.assertEqual(self.call("POST", "/skills", self.a, json={"name": "Record keeping"}).status_code, 200)
        self.assertEqual(self.call("POST", "/education", self.a, json={"institution": "Fictional School B", "degree": "Certificate",
                                                                        "field_of_study": "Customer Service"}).status_code, 200)

    # ---- helpers -----------------------------------------------------------------------------------------------------------
    def _build(self, mode):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": copy.deepcopy(CONTENT)}):
            res = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B",
                                                                           "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["resume_version_id"]

    def _legacy(self, vid, mode="on", who=None, query=""):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}):
            return self.call("GET", f"/resume-versions/{vid}/download{query}", who or self.a)

    def _document(self, vid, mode="on"):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}):
            return self.call("GET", f"/resume-versions/{vid}/document", self.a)

    def _review(self, vid):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            return self.call("GET", f"/resume-versions/{vid}/review", self.a).json()

    def _sign(self, vid):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            for item in self._review(vid)["items"]:
                if item["classification"] == "UNCERTAIN" and item["decision"] is None:
                    self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.a,
                                               json={"item_id": item["id"], "decision": "keep", "acknowledge": True}).status_code, 200)
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview.json()["finalized_hash"]}).status_code, 200)

    def _write_legacy(self, vid, extra=None):
        """Turns a stored version into a plain pre-truth-check version (no review) for the legacy cases."""
        with self.Session() as s:
            v = s.get(ResumeVersion, vid)
            data = {k: x for k, x in (v.resume_data or {}).items() if k not in ("truth_review", "final_signoff")}
            data.update(extra or {})
            v.resume_data = data
            s.commit()

    # ---- 1. review-required version, switch ON --------------------------------------------------------------------------
    def test_direct_legacy_request_is_refused_for_an_unsigned_review_required_general_resume(self):
        vid = self._build("on")
        self.assertEqual(self._legacy(vid, "on").status_code, 409)
        self.assertEqual(self._document(vid, "on").status_code, 409)

    def test_signed_legacy_request_returns_the_same_bytes_as_the_signed_document(self):
        vid = self._build("on")
        self._sign(vid)
        legacy = self._legacy(vid, "on")
        signed = self._document(vid, "on")
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertEqual(legacy.content, signed.content)

    def test_legacy_request_in_ats_mode_is_refused_for_a_signed_review_required_resume(self):
        vid = self._build("on")
        self._sign(vid)
        self.assertEqual(self._legacy(vid, "on", query="?ats_mode=true").status_code, 409)

    def test_an_edit_after_sign_off_blocks_the_legacy_download_until_it_is_signed_again(self):
        vid = self._build("on")
        self._sign(vid)
        target = next(i for i in self._review(vid)["items"] if i["where"] == "summary[1]")
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.a, json={
                "item_id": target["id"], "decision": "edit", "acknowledge": False,
                "text": "Coordinator and record keeper for a small office team."}).status_code, 200)
        self.assertEqual(self._legacy(vid, "on").status_code, 409)

    def test_a_saved_fact_change_after_sign_off_blocks_the_legacy_download(self):
        vid = self._build("on")
        self._sign(vid)
        exp = self.call("GET", "/experiences", self.a).json()[0]
        self.assertEqual(self.call("PUT", f"/experiences/{exp['id']}", self.a, json={
            "title": "Coordinator", "organization": "Fictional Organization Beta", "description": "Changed after the sign-off.",
            "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        self.assertEqual(self._legacy(vid, "on").status_code, 409)

    # ---- 2. legacy versions -----------------------------------------------------------------------------------------------
    def test_a_legacy_general_resume_is_refused_while_the_switch_is_on(self):
        vid = self._build("off")
        self.assertEqual(self._legacy(vid, "on").status_code, 409)
        self.assertIn(LEGACY_REFUSAL, self._legacy(vid, "on").text)

    def test_a_legacy_general_resume_is_still_served_while_the_switch_is_off_or_shadow(self):
        vid = self._build("off")
        self.assertEqual(self._legacy(vid, "off").status_code, 200)
        self.assertEqual(self._legacy(vid, "shadow").status_code, 200)

    def test_a_job_targeted_version_without_a_member_review_is_served_only_while_the_switch_is_off_or_shadow(self):
        vid = self._build("off")
        self._write_legacy(vid, {"term_report": []})          # the job-targeted kind, as the job build stores it (no member review)
        for mode in ("off", "shadow"):
            with self.subTest(mode=mode):
                self.assertEqual(self._legacy(vid, mode).status_code, 200)
        self.assertEqual(self._legacy(vid, "on").status_code, 409)   # an unreviewed job version cannot bypass sign-off

    # ---- 3. switch modes for a review-required version (enforcement only when ON) ----------------------------------------
    def test_shadow_and_off_do_not_enforce_on_a_review_required_resume(self):
        vid = self._build("shadow")
        self.assertEqual(self._legacy(vid, "shadow").status_code, 200)
        self.assertEqual(self._legacy(vid, "off").status_code, 200)

    # ---- 4. ownership and authentication are unconditional -----------------------------------------------------------------
    def test_another_member_gets_404_from_the_legacy_endpoint_in_every_mode(self):
        vid = self._build("on")
        self._sign(vid)
        self.onboard(self.b)
        for mode in ("off", "shadow", "on"):
            with self.subTest(mode=mode):
                self.assertEqual(self._legacy(vid, mode, who=self.b).status_code, 404)

    def test_the_legacy_endpoint_needs_a_signed_in_member(self):
        vid = self._build("off")
        self.assertIn(self.client.get(f"/api/career/resume-versions/{vid}/download").status_code, (401, 403))

    # ---- 5. the public tools are untouched --------------------------------------------------------------------------------
    def test_the_anonymous_generate_endpoint_still_requires_no_sign_in_and_is_not_a_member_route(self):
        main_src = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf8").read()
        block = main_src[main_src.index('@app.post("/api/generate")'):]
        block = block[:block.index("\n\n\n")] if "\n\n\n" in block else block
        self.assertNotIn("get_current_user", block)
        self.assertIsNotNone(re.search(r"async def api_generate\(req: GenerateRequest\)", block))


class JobVersionApprovalWhileOn(DownloadEnforcement):
    """Documents the current, safe refusal until the job-targeted integration: a job-kind version cannot be approved while the switch
    is ON (its own truth_review is not the general review, so the approval refuses rather than trusting it)."""

    def test_a_job_targeted_version_cannot_be_approved_while_the_switch_is_on(self):
        from career.opportunities import router as opportunities_router
        self.client.app.include_router(opportunities_router, prefix="/api/career")
        with mock.patch.dict(os.environ, {"CT_OPPORTUNITIES_ENABLED": "1", "CT_OPPORTUNITIES_ALLOWED_SUBS": f"{SUB_A},{SUB_B}"}):
            vid = self._build("off")
            self._write_legacy(vid, {"term_report": [], "truth_review": {"claim_review": [], "answer_conflicts": []}})
            oid = self.call("POST", "/opportunities", self.a, json={"title": "Analyst", "employer": "Sample",
                                                                     "job_url": "https://jobs.example-employer.com/p/9",
                                                                     "location_text": "Chicago, IL", "work_arrangement": "hybrid",
                                                                     "employment_type": "full_time"}).json()["id"]
            with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
                res = self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid})
        self.assertEqual(res.status_code, 409, res.text)


class HistoryPageUsesTheSameRule(unittest.TestCase):
    def test_the_history_download_goes_through_the_legacy_endpoint_and_shows_the_servers_words(self):
        here = os.path.dirname(__file__)
        with open(os.path.join(here, "..", "..", "frontend", "career", "js", "history.js"), encoding="utf8") as f:
            src = f.read()
        self.assertIn('"/api/career/resume-versions/" + entry.id + "/download', src)
        self.assertIn("resumeDownloadErrorText(err)", src)      # a refused download shows the server's reason, not a silent failure
        self.assertNotIn("/api/generate", src)


if __name__ == "__main__":
    unittest.main()
