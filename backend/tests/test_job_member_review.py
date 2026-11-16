"""C-52 round 7: job-targeted résumés use the common member review, built from the job pipeline's OWN records.

A) The keys: the common member review is separate from the job pipeline's truth_review. A job-specific truth_review is never read as a
   member review, and is never changed.
B) Mapping: the job pipeline's supported, derived, uncertain, held and removed statements become review items with their original
   evidence. Nothing is classified as supported without evidence (the job term record, or an exact match to saved information).
C) Flow (switch ON): decisions, edit, preview, explicit sign-off and the signed download; stale sign-offs; cross-member access.
D) Approval and downloads: an unreviewed job version cannot be approved or downloaded with the switch ON; a recorded résumé is historical
   evidence (no decisions, edits, sign-off or recheck); the owner-initiated recheck of an older job version uses saved information only.

The job pipeline's AI call is replaced by a fixture with the same shape as its output (no paid call).
Run from the backend folder:  py -3.12 -m unittest tests.test_job_member_review -v
"""
import copy
import os
import unittest
from unittest import mock

import abuse_guard
from career import member_review as mr
from career import review_gate as rg
from models import ResumeVersion
from tests.test_ownership import OwnershipTestCase, SUB_A, SUB_B

FACTS = {
    "roles": [{"id": 1, "title": "Coordinator", "organization": "Fictional Organization Beta", "years": [2021, 2025],
               "start": (2021, 6), "end": (2025, 5), "text": "Improved the record-keeping checklist. Handled customer requests."}],
    "education": [{"id": 1, "school": "Fictional School B", "degree": "Certificate Customer Service", "text": ""}],
    "skills": ["Record keeping"],
    "certifications": [],
}

RESUME = {
    "name": "SYNTHETIC Member B", "contact": "SYNTHETIC | synthetic.member.b@example.com",
    "headline": "Coordinator",
    "summary": "Handled customer requests.",
    "skills": ["Record keeping", "Calendar planning", "Customer care"],
    "experience": [{"title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
                    "bullets": ["Improved the record-keeping checklist.", "Led a team of twelve."]}],
    "education": ["Fictional School B: Certificate, Customer Service"], "certifications": [], "skills_style": "grouped",
}

# The shape of the job pipeline's result (its own records), as build_checked_resume returns it.
PIPELINE_RESULT = {
    "resume_data": RESUME,
    "term_report": [
        {"term": "Record keeping", "kind": "skill", "importance": "high", "support": "literal", "evidence": "Record keeping (Coordinator)", "status": "placed"},
        {"term": "Calendar planning", "kind": "skill", "importance": "medium", "support": "transferable", "evidence": "scheduled team meetings", "status": "placed"},
        {"term": "Process improvement", "kind": "skill", "importance": "medium", "support": "none", "evidence": "", "status": "not_placed"},
    ],
    "claim_review": [{"where": "bullet under \"Coordinator\"", "problem": "unsupported claim: team size not in the candidate's profile", "text": "Led a team of twelve."}],
    "verb_review": [], "fact_verb_review": [], "verbs_restored": [],
    "claims_struck": [{"where": "summary", "text": "Known for dependable work.", "reason": "a soft claim with no source in the saved information"}],
    "skills_removed": ["Process improvement"],
    "lines_held": [{"where": "bullet under \"Coordinator\"", "text": "Managed a budget of 5000.", "written": "Managed",
                    "evidence_verb": "helped", "problem": "could not be restored safely; held for confirmation"}],
    "answer_conflicts": [], "role_selection": [], "ats_match": None, "truth_notice": {"count": 0},
}
JOB_TEXT = ("Coordinator role for a fictional employer. Keep records, schedule meetings, and support customers. " * 4)


class MappingFromPipelineRecords(unittest.TestCase):
    """B: the job pipeline's own records become review items, with their evidence; nothing is invented."""

    def setUp(self):
        self.review = rg.job_review(copy.deepcopy(RESUME), copy.deepcopy(PIPELINE_RESULT), FACTS, now=None)

    def test_a_term_the_pipeline_found_in_saved_information_is_supported_with_its_evidence(self):
        row = next(r for r in self.review["supported"] if r["where"] == "skills[0]")
        self.assertEqual(row["classification"], "SUPPORTED")
        self.assertIn("Record keeping (Coordinator)", row["source"])

    def test_a_transferable_skill_is_derived_with_its_evidence_and_is_not_a_review_item(self):
        row = next(r for r in self.review["derived"] if r["where"] == "skills[1]")
        self.assertEqual(row["classification"], "DERIVED")
        self.assertIn("scheduled team meetings", row["source"])
        self.assertFalse(any(i["where"] == "skills[1]" for i in self.review["items"]))

    def test_a_statement_the_pipeline_could_not_confirm_is_uncertain_with_the_pipelines_reason(self):
        item = next(i for i in self.review["items"] if i["where"] == "experience[0].bullets[1]")
        self.assertEqual(item["classification"], "UNCERTAIN")
        self.assertIsNone(item["decision"])
        self.assertIn("could not confirm", item["explanation"])

    def test_an_exact_match_to_saved_information_is_supported_and_the_rest_are_uncertain_never_supported(self):
        supported_where = {r["where"] for r in self.review["supported"]}
        self.assertIn("experience[0].bullets[0]", supported_where)   # exact saved sentence
        self.assertIn("headline[0]", supported_where)                 # exact held title
        uncertain = {i["where"] for i in self.review["items"]}
        self.assertIn("skills[2]", uncertain)                         # "Customer care": no evidence, no match, not invented as supported
        self.assertFalse(any(i["classification"] == "UNSUPPORTED" for i in self.review["items"]))

    def test_removed_and_held_statements_keep_the_pipelines_own_reason(self):
        texts = {r["text"]: r["explanation"] for r in self.review["removed"]}
        self.assertIn("Known for dependable work.", texts)
        self.assertIn("a soft claim", texts["Known for dependable work."])
        self.assertIn("Process improvement", texts)
        self.assertIn("Managed a budget of 5000.", texts)
        self.assertIn("Held out of the résumé", texts["Managed a budget of 5000."])

    def test_the_mapping_is_deterministic(self):
        again = rg.job_review(copy.deepcopy(RESUME), copy.deepcopy(PIPELINE_RESULT), FACTS, now=None)
        strip = lambda r: {k: v for k, v in r.items() if k not in ("created_at",)}
        self.assertEqual(strip(self.review), strip(again))

    def test_the_review_is_bound_to_the_content_and_the_saved_facts(self):
        self.assertEqual(self.review["content_hash"], rg.content_hash(RESUME))
        self.assertEqual(self.review["facts_hash"], rg.facts_hash(FACTS))


class KeysAndKinds(unittest.TestCase):
    """A: a job-specific truth_review is never mistaken for a member review, and the legacy general keys still read."""

    JOB_TRUTH = {"answer_conflicts": [], "claims_struck": [], "claim_review": [], "verb_review": [], "lines_held": []}

    def test_a_job_truth_review_is_never_read_as_a_member_review(self):
        data = {**RESUME, "term_report": [], "truth_review": copy.deepcopy(self.JOB_TRUTH)}
        self.assertIsNone(mr.review_of(data))
        self.assertEqual(mr.kind_of(data), "job")

    def test_a_job_version_with_a_member_review_is_read_from_the_common_key(self):
        review = rg.job_review(RESUME, PIPELINE_RESULT, FACTS)
        data = mr.with_review({**RESUME, "term_report": [], "truth_review": copy.deepcopy(self.JOB_TRUTH)}, review)
        self.assertIs(mr.review_of(data), data["member_review"])
        self.assertEqual(data["truth_review"], self.JOB_TRUTH)           # the job's own record is untouched
        self.assertEqual(mr.kind_of(data), "job")

    def test_a_legacy_general_review_is_still_read_and_moved_on_write(self):
        legacy_review = {"checker_version": "step-a-rev3", "content_hash": "x", "facts_hash": "y", "items": []}
        data = {**RESUME, "truth_review": legacy_review}
        self.assertEqual(mr.kind_of(data), "general_review")
        self.assertIs(mr.review_of(data), legacy_review)
        moved = mr.with_review(data, {"checker_version": "new"})
        self.assertNotIn("truth_review", moved)
        self.assertEqual(moved["member_review"]["checker_version"], "new")

    def test_a_legacy_general_sign_off_is_read_and_moved(self):
        data = {**RESUME, "final_signoff": {"finalized_hash": "h"}}
        self.assertEqual(mr.signoff_of(data), {"finalized_hash": "h"})
        self.assertNotIn("final_signoff", mr.with_signoff(data, {"finalized_hash": "h"}))

    def test_a_saved_résumé_with_no_review_is_a_general_legacy_version(self):
        self.assertEqual(mr.kind_of(dict(RESUME)), "general_legacy")

    def test_review_keys_are_excluded_from_content_hashes_as_before(self):
        base = rg.content_hash(RESUME)
        self.assertEqual(base, rg.content_hash({**RESUME, "member_review": {"x": 1}, "member_signoff": {"y": 2}}))
        self.assertEqual(base, rg.content_hash({**RESUME, "truth_review": {"answer_conflicts": []}}))


class ReviewChangesRegression(unittest.TestCase):
    """Data round 8 display correction: a change of classification across lists is reported as a change; a statement still in the
    résumé is never described as removed or as no longer in the résumé."""

    def _row(self, where, text, cls, why="explained"):
        return {"where": where, "text": text, "classification": cls, "explanation": why}

    def _review(self, items=(), supported=(), derived=(), removed=()):
        return {"items": list(items), "supported": list(supported), "derived": list(derived), "removed": list(removed)}

    def test_uncertain_to_supported_is_a_classification_change_and_not_a_removal(self):
        text = "Improved the record-keeping checklist."
        prev = self._review(items=[self._row("experience[0].bullets[0]", text, "UNCERTAIN")])
        cur = self._review(supported=[self._row("experience[0].bullets[0]", text, "SUPPORTED")])
        changes = rg.review_changes(prev, cur)
        self.assertEqual([c["kind"] for c in changes], ["classification"])
        self.assertEqual((changes[0]["before"], changes[0]["after"]), ("UNCERTAIN", "SUPPORTED"))
        self.assertFalse(any(c["kind"] == "no longer in the review" for c in changes))

    def test_supported_to_uncertain_is_a_classification_change(self):
        text = "Improved the record-keeping checklist."
        prev = self._review(supported=[self._row("experience[0].bullets[0]", text, "SUPPORTED")])
        cur = self._review(items=[self._row("experience[0].bullets[0]", text, "UNCERTAIN")])
        changes = rg.review_changes(prev, cur)
        self.assertEqual([(c["kind"], c["before"], c["after"]) for c in changes], [("classification", "SUPPORTED", "UNCERTAIN")])

    def test_a_statement_still_in_the_resume_is_never_called_removed(self):
        derived = [self._row("skills[1]", "Calendar planning", "DERIVED")]
        prev = self._review(derived=derived)
        cur = self._review(derived=derived, removed=[{"where": "skills", "text": "Calendar planning", "explanation": "Removed."}])
        self.assertEqual(rg.review_changes(prev, cur), [])

    def test_a_statement_still_present_under_another_list_is_not_called_removed_either(self):
        prev = self._review(items=[self._row("skills[0]", "Record keeping", "UNCERTAIN")])
        cur = self._review(supported=[self._row("skills[0]", "Record keeping", "SUPPORTED")],
                           removed=[{"where": "skills", "text": "Record keeping", "explanation": "Removed."}])
        changes = rg.review_changes(prev, cur)
        self.assertEqual([c["kind"] for c in changes], ["classification"])

    def test_a_statement_that_left_the_resume_is_reported_as_no_longer_in_the_review(self):
        prev = self._review(items=[self._row("experience[0].bullets[1]", "Led a team of twelve.", "UNCERTAIN")])
        changes = rg.review_changes(prev, self._review())
        self.assertEqual([(c["kind"], c["text"], c["after"]) for c in changes],
                         [("no longer in the review", "Led a team of twelve.", "not in the résumé")])

    def test_a_newly_removed_statement_is_reported_once(self):
        removed = [{"where": "skills", "text": "Process improvement", "explanation": "Removed: no basis in your saved information."}]
        first = rg.review_changes(self._review(), self._review(removed=removed))
        self.assertEqual([(c["kind"], c["text"]) for c in first], [("removed", "Process improvement")])
        self.assertEqual(rg.review_changes(self._review(removed=removed), self._review(removed=removed)), [])

    def test_with_no_previous_review_every_statement_is_reported_as_not_reviewed_before(self):
        cur = self._review(items=[self._row("headline[0]", "Coordinator", "UNCERTAIN")])
        changes = rg.review_changes(None, cur)
        self.assertEqual([(c["kind"], c["before"]) for c in changes], [("classification", "not reviewed before")])


class JobFlow(OwnershipTestCase):
    """C and D: the job build, the review, sign-off, downloads and approval, through the real routes (AI call replaced by the fixture)."""

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
            "description": "Improved the record-keeping checklist. Handled customer requests.", "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        self.assertEqual(self.call("POST", "/skills", self.a, json={"name": "Record keeping"}).status_code, 200)

    def _job_build(self, mode="on", who=None):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": mode}), \
                mock.patch("career.routes.build_checked_resume", return_value=copy.deepcopy(PIPELINE_RESULT)):
            res = self.call("POST", "/job-build-resume", who or self.a, json={"job_description": JOB_TEXT, "name": "SYNTHETIC Member B",
                                                                              "contact": "SYNTHETIC | synthetic.member.b@example.com"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _review(self, vid, who=None):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            return self.call("GET", f"/resume-versions/{vid}/review", who or self.a)

    def _decide(self, vid, item_id, decision, text=None, ack=False):
        body = {"item_id": item_id, "decision": decision, "acknowledge": ack}
        if text is not None:
            body["text"] = text
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            return self.call("POST", f"/resume-versions/{vid}/decisions", self.a, json=body)

    def _sign(self, vid):
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            body = self._review(vid).json()
            for item in body["items"]:
                if item["classification"] == "UNCERTAIN" and item["decision"] is None:
                    self.assertEqual(self._decide(vid, item["id"], "keep", ack=True).status_code, 200)
            preview = self.call("GET", f"/resume-versions/{vid}/preview", self.a)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json()["can_sign_off"])
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/signoff", self.a,
                                       json={"finalized_hash": preview.json()["finalized_hash"]}).status_code, 200)

    def _job_item(self, vid, where):
        return next(i for i in self._review(vid).json()["items"] if i["where"] == where)

    # ---- C: the review flow on a job-targeted résumé -----------------------------------------------------------------------
    def test_a_job_build_stores_the_member_review_and_keeps_the_jobs_own_record(self):
        body = self._job_build("on")
        self.assertEqual(body["truth_gate"], "on")
        stored = next(v for v in self.call("GET", "/resume-versions", self.a).json() if v["id"] == body["resume_version_id"])["resume_data"]
        self.assertIn("member_review", stored)
        self.assertEqual(stored["truth_review"]["lines_held"], PIPELINE_RESULT["lines_held"])   # the job's own record, unchanged
        self.assertNotIn("checker_version", stored["truth_review"])

    def test_the_job_review_screen_gets_the_pipelines_sections_and_its_uncertain_statements(self):
        vid = self._job_build("on")["resume_version_id"]
        body = self._review(vid).json()
        self.assertEqual(body["status"], "needs_review")
        self.assertTrue(any(r["where"] == "skills[0]" for r in body["supported"]))
        self.assertTrue(any(r["where"] == "skills[1]" for r in body["derived"]))
        self.assertTrue(any(i["where"] == "experience[0].bullets[1]" for i in body["items"]))

    def test_keep_edit_remove_and_preview_and_sign_off_work_on_a_job_version(self):
        vid = self._job_build("on")["resume_version_id"]
        led = self._job_item(vid, "experience[0].bullets[1]")
        self.assertEqual(self._decide(vid, led["id"], "keep", ack=False).status_code, 400)          # acknowledgement required
        self.assertEqual(self._decide(vid, led["id"], "edit", text="Led a small team of volunteers.").status_code, 409)  # unverified wording refused
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 200)

    def test_a_decision_after_sign_off_makes_the_job_download_stale(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        led = self._job_item(vid, "experience[0].bullets[1]")
        self.assertEqual(self._decide(vid, led["id"], "remove").status_code, 200)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)

    def test_an_edit_to_a_supported_wording_clears_the_sign_off_and_the_statement_is_checked_again(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        other = self._job_item(vid, "skills[2]")                               # "Customer care": uncertain
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self._decide(vid, other["id"], "edit", text="Record keeping").status_code, 200)   # exact saved skill
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)
            stored = next(v for v in self.call("GET", "/resume-versions", self.a).json() if v["id"] == vid)["resume_data"]
        self.assertNotIn("member_signoff", stored)
        self.assertIn("Record keeping", stored["skills"])

    def test_a_saved_fact_change_after_sign_off_makes_the_job_download_stale(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        exp = self.call("GET", "/experiences", self.a).json()[0]
        self.assertEqual(self.call("PUT", f"/experiences/{exp['id']}", self.a, json={
            "title": "Coordinator", "organization": "Fictional Organization Beta", "description": "Changed after the sign-off.",
            "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/download", self.a).status_code, 409)

    def test_another_member_cannot_read_decide_sign_or_download_a_job_review(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        self.onboard(self.b)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/review", self.b).status_code, 404)
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.b).status_code, 404)
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/download", self.b).status_code, 404)
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.b,
                                       json={"item_id": "x", "decision": "keep", "acknowledge": True}).status_code, 404)

    # ---- D: approvals, legacy downloads, recorded résumés, recheck ----------------------------------------------------------
    def _opportunity(self):
        res = self.call("POST", "/opportunities", self.a, json={"title": "Coordinator", "employer": "Sample Employer",
                                                                 "job_url": "https://jobs.example-employer.com/job/" + os.urandom(3).hex(),
                                                                 "location_text": "Chicago, IL", "work_arrangement": "hybrid",
                                                                 "employment_type": "full_time"})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["id"]

    def test_an_unreviewed_job_version_cannot_be_downloaded_or_approved_with_the_switch_on(self):
        vid = self._job_build("off")["resume_version_id"]        # built while OFF: no member review
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/download", self.a).status_code, 409)
            oid = self._opportunity()
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid}).status_code, 409)

    def test_a_signed_job_version_can_be_approved_and_its_approved_document_is_kept(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            oid = self._opportunity()
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid}).status_code, 200)
            self.assertEqual(self.call("GET", f"/opportunities/{oid}/approved-document", self.a).status_code, 200)

    def test_a_recorded_job_version_is_historical_evidence_and_cannot_be_changed(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            oid = self._opportunity()
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid}).status_code, 200)
            rec = self.call("POST", f"/opportunities/{oid}/record-application", self.a, json={"applied_on": "2026-11-11"})
            self.assertEqual(rec.status_code, 200, rec.text)
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/decisions", self.a,
                                       json={"item_id": "x", "decision": "keep", "acknowledge": True}).status_code, 409)
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 409)
            self.assertEqual(self.call("GET", f"/opportunities/{oid}/approved-document", self.a).status_code, 200)

    def test_the_owner_can_recheck_an_older_job_version_from_saved_information_without_an_ai_call(self):
        vid = self._job_build("off")["resume_version_id"]
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}), \
                mock.patch("career.job_match.build_tailored_resume", side_effect=AssertionError("no AI call")):
            res = self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a)
            self.assertEqual(res.status_code, 200, res.text)
            again = self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a)
            self.assertEqual(again.status_code, 409)                 # already checked
            self.assertEqual(self._review(vid).status_code, 200)

    def test_a_job_version_whose_content_or_facts_changed_is_checked_again_and_its_old_sign_off_is_cleared(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        exp = self.call("GET", "/experiences", self.a).json()[0]
        self.assertEqual(self.call("PUT", f"/experiences/{exp['id']}", self.a, json={
            "title": "Coordinator", "organization": "Fictional Organization Beta", "description": "Changed after the sign-off.",
            "start_date": "06/21", "end_date": "05/25"}).status_code, 200)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self._review(vid).status_code, 409)               # stale
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 200)
            self.assertEqual(self._review(vid).status_code, 200)               # current again, decisions to be made
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)   # sign-off cleared
        stored = next(v for v in self.call("GET", "/resume-versions", self.a).json() if v["id"] == vid)["resume_data"]
        self.assertNotIn("member_signoff", stored)

    def test_a_general_résumé_saved_before_the_check_is_not_rechecked_this_way(self):
        self.onboard(self.b)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "off"}), \
                mock.patch("career.routes.build_general_resume", return_value={"resume_data": copy.deepcopy(RESUME)}):
            vid = self.call("POST", "/build-general-resume", self.a, json={"name": "SYNTHETIC Member B",
                                                                           "contact": "SYNTHETIC | synthetic.member.b@example.com"}).json()["resume_version_id"]
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 409)

    def test_the_recheck_of_another_members_version_is_not_found(self):
        vid = self._job_build("off")["resume_version_id"]
        self.onboard(self.b)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.b).status_code, 404)


class JobRecheckPreservesEvidence(JobFlow):
    """Round 8: the job pipeline's own truth_review survives every member action and a recheck; a recheck uses the job's saved evidence,
    never changes the résumé text, keeps the previous review, and a stale sign-off cannot be reused."""

    def _stored(self, vid):
        return next(v for v in self.call("GET", "/resume-versions", self.a).json() if v["id"] == vid)["resume_data"]

    def _make_stale(self):
        exp = self.call("GET", "/experiences", self.a).json()[0]
        self.assertEqual(self.call("PUT", f"/experiences/{exp['id']}", self.a, json={
            "title": "Coordinator", "organization": "Fictional Organization Beta", "description": "Changed after the review.",
            "start_date": "06/21", "end_date": "05/25"}).status_code, 200)

    def test_the_jobs_truth_review_survives_a_stale_recheck_unchanged(self):
        vid = self._job_build("on")["resume_version_id"]
        original = self._stored(vid)["truth_review"]
        self._make_stale()
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 200)
        self.assertEqual(self._stored(vid)["truth_review"], original)
        self.assertIn("lines_held", original)
        self.assertEqual(self._stored(vid)["truth_review"]["lines_held"], PIPELINE_RESULT["lines_held"])

    def test_the_jobs_truth_review_survives_decisions_and_sign_off(self):
        vid = self._job_build("on")["resume_version_id"]
        original = self._stored(vid)["truth_review"]
        self._sign(vid)
        self.assertEqual(self._stored(vid)["truth_review"], original)

    def test_a_recheck_never_changes_the_resume_text_and_keeps_the_previous_review(self):
        vid = self._job_build("on")["resume_version_id"]
        before = self._stored(vid)
        self._make_stale()
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            res = self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a)
        self.assertEqual(res.status_code, 200, res.text)
        after = self._stored(vid)
        for key in ("skills", "experience", "headline", "summary", "term_report", "education", "name", "contact"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(len(after["member_review_history"]), 1)
        self.assertIn("items", after["member_review_history"][0]["review"])
        self.assertIsInstance(res.json()["changes"], list)

    def test_a_recheck_uses_the_jobs_saved_evidence_not_the_general_checker_alone(self):
        vid = self._job_build("off")["resume_version_id"]         # no member review yet: the job record is the only evidence
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 200)
        review = self._stored(vid)["member_review"]
        led = next(i for i in review["items"] if i["where"] == "experience[0].bullets[1]")
        self.assertEqual(led["classification"], "UNCERTAIN")
        self.assertIn("could not confirm", led["explanation"])               # the pipeline's own reason, quoted from its record
        self.assertEqual(review["source"], "job_pipeline")

    def test_a_stale_sign_off_cannot_be_reused_after_a_recheck(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self._make_stale()
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 200)
            self.assertEqual(self.call("GET", f"/resume-versions/{vid}/document", self.a).status_code, 409)
        self.assertNotIn("member_signoff", self._stored(vid))

    def test_a_recheck_of_a_recorded_version_names_the_recorded_application(self):
        # F5 (Data 2026-11-15): the refusal explains that a recorded application prevents changes, even for a version already checked.
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            oid = self._opportunity()
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid}).status_code, 200)
            self.assertEqual(self.call("POST", f"/opportunities/{oid}/record-application", self.a, json={"applied_on": "2026-11-11"}).status_code, 200)
            res = self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a)
        self.assertEqual(res.status_code, 409)
        self.assertIn("recorded", res.json()["detail"])
        self.assertNotIn("already been checked", res.json()["detail"])

    def test_a_recorded_job_version_is_not_rechecked_and_its_frozen_document_is_unchanged(self):
        vid = self._job_build("on")["resume_version_id"]
        self._sign(vid)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            oid = self._opportunity()
            self.assertEqual(self.call("PUT", f"/opportunities/{oid}/approval", self.a, json={"approved_resume_version_id": vid}).status_code, 200)
            self.assertEqual(self.call("POST", f"/opportunities/{oid}/record-application", self.a, json={"applied_on": "2026-11-11"}).status_code, 200)
            doc_before = self.call("GET", f"/opportunities/{oid}/approved-document", self.a).content
            stored_before = self._stored(vid)
            self._make_stale()
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.a).status_code, 409)
            self.assertEqual(self.call("GET", f"/opportunities/{oid}/approved-document", self.a).content, doc_before)
        self.assertEqual(self._stored(vid)["truth_review"], stored_before["truth_review"])

    def test_only_the_owner_can_recheck_and_another_member_gets_404(self):
        vid = self._job_build("off")["resume_version_id"]
        self.onboard(self.b)
        with mock.patch.dict(os.environ, {"CT_GENERAL_RESUME_TRUTH_GATE": "on"}):
            self.assertEqual(self.call("POST", f"/resume-versions/{vid}/member-recheck", self.b).status_code, 404)
            self.assertIn(self.client.post(f"/api/career/resume-versions/{vid}/member-recheck").status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
