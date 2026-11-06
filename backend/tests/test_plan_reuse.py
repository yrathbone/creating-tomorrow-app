"""Priority 1, PR 3: plan reuse. The keyword step already asked the AI which posting terms the profile supports; the plan is kept with the job
comparison (no new table) and the build re-checks it against the evidence as it is then, so one posting costs one planning call, not two.
Fictional data, stand-in AI, no live calls.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import os
import unittest
from unittest import mock

import abuse_guard
from career import job_match, term_pipeline
from models import ScanHistory
from tests.test_ownership import SUB_A, OwnershipTestCase

POSTING = "Customer Success Associate\nRun onboarding calls with new customers, resolve cases in ticketing software, and calm upset customers using de-escalation."
PROFILE = """EXPERIENCE:
- Shift Lead at Hearthside Home Goods (2021 - Present)
  * Handled returns and customer complaints, about 20 a week
  * Trained new hires on the POS system
SKILLS (not tied to one specific role):
- De-escalation"""


def term(name, support, evidence="", importance="required", group="", kind="skill"):
    return {"term": name, "importance": importance, "kind": kind, "support": support, "evidence": evidence, "denied": False,
            "alternatives_group": group, "accepts_equivalent_experience": False}


class A_ReguardingASavedPlan(unittest.TestCase):
    def reguard(self, saved, facts="", denials=None, profile=PROFILE):
        return {t["term"]: t["support"] for t in term_pipeline.reguard_saved_terms(saved, profile, facts, POSTING, denials)}

    def test_a_reused_plan_makes_no_ai_call(self):
        with mock.patch.object(job_match, "_call_with_retry", side_effect=AssertionError("no AI call expected")):
            self.reguard([term("De-escalation", "literal")])

    def test_a_term_the_candidate_confirmed_since_becomes_literal(self):
        out = self.reguard([term("Onboarding calls", "none")], facts="- Ran onboarding calls with new customers")
        self.assertEqual(out["Onboarding calls"], "literal")

    def test_a_new_denial_removes_support(self):
        saved = [term("Customer onboarding", "related", "Trained new hires")]
        out = self.reguard(saved, denials=[{"question": "Have you done customer onboarding?", "answer": "No"}])
        self.assertEqual(out["Customer onboarding"], "none")

    def test_a_literal_term_no_longer_in_the_evidence_is_never_carried_as_supported(self):
        out = self.reguard([term("Salesforce", "literal", "Used Salesforce")])
        self.assertEqual(out["Salesforce"], "none")

    def test_related_keeps_its_reason_and_unevidenced_related_is_dropped(self):
        out = self.reguard([term("Complaint handling", "related", "Handled returns and customer complaints"), term("Ticketing software", "related", "")])
        self.assertEqual((out["Complaint handling"], out["Ticketing software"]), ("related", "none"))

    def test_hedged_related_evidence_is_still_demoted_on_reuse(self):
        out = self.reguard([term("Customer success", "related", "Has not held that title; a different role")])
        self.assertEqual(out["Customer success"], "transferable")

    def test_alternatives_groups_survive_reuse(self):
        out = term_pipeline.reguard_saved_terms([term("PMP", "none", group="credential"), term("PRINCE2", "none", group="credential")], PROFILE, "", POSTING)
        self.assertEqual([t["alternatives_group"] for t in out], ["credential", "credential"])


class B_TheBuildReportDoesNotCallAnUnmetAlternativeAGap(unittest.TestCase):
    def build(self, plan):
        built = {"summary": "Shift lead.", "skills": ["De-escalation"], "experience": [], "education": [], "certifications": []}

        def fake(name, system, user, tool, extract=None):
            if name == "career_term_plan":
                return {"terms": plan}
            if name == "career_job_build_resume":
                return {"resume_data": built}
            raise job_match.JobMatchError("edit unavailable")

        with mock.patch.object(job_match, "_call_with_retry", fake):
            return term_pipeline.build_checked_resume(PROFILE, POSTING, [], "N", "c@example.com")

    def statuses(self, result):
        return {r["term"]: r["status"] for r in result["term_report"]}

    def test_the_unmet_member_of_a_met_group_is_alternative_met(self):
        plan = [term("PMP", "none", group="credential"), term("De-escalation", "literal", group="credential")]
        self.assertEqual(self.statuses(self.build(plan))["PMP"], "alternative_met")

    def test_an_unmet_group_stays_a_gap(self):
        plan = [term("PMP", "none", group="credential"), term("PRINCE2", "none", group="credential")]
        self.assertEqual(set(self.statuses(self.build(plan)).values()), {"not_in_profile"})


class C_TheRoutesKeepAndReuseThePlan(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
                        mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()
        self.onboard(self.a)
        self.call("POST", "/experiences", self.a, json={"title": "Shift Lead", "organization": "Hearthside Home Goods", "description": "Handled returns and customer complaints"})
        with self.Session() as s:
            scan = ScanHistory(career_profile_id=self.profile_id_for(SUB_A), scan_type="job_comparison", job_title="CSA", summary_text="s",
                               result_data={"job_description": POSTING, "qa_history": []})
            s.add(scan)
            s.commit()
            self.scan_id = scan.id
        self.plan = [term("De-escalation", "literal", importance="required"), term("Ticketing software", "none")]

    def keyword_check(self, scan_id="default", posting=POSTING, who=None):
        body = {"job_description": posting}
        if scan_id == "default":
            scan_id = self.scan_id
        if scan_id is not None:
            body["scan_history_id"] = scan_id
        with mock.patch("career.routes.keyword_check_with_plan", return_value=({"terms": [], "already_covered": 0}, self.plan)):
            return self.call("POST", "/job-keyword-check", who or self.a, json=body)

    def build(self, posting=POSTING):
        seen = {}

        def fake_build(profile_text, job_description, confirmed_facts, name, contact, denials, answers_text="", saved_terms=None):
            seen["saved_terms"] = saved_terms
            return {"resume_data": {"summary": "s", "skills": [], "experience": [], "education": [], "certifications": []}, "role_selection": [], "term_report": [], "ats_match": None}

        with mock.patch("career.routes.build_checked_resume", fake_build):
            res = self.call("POST", "/job-build-resume", self.a, json={
                "job_description": posting, "name": "Marcus Bell", "contact": "Naperville, IL | m@example.com",
                "confirmed_facts": [], "qa_history": [], "scan_history_id": self.scan_id})
        self.assertEqual(res.status_code, 200, res.text)
        return seen["saved_terms"]

    def test_the_keyword_step_keeps_the_plan_with_the_job_comparison(self):
        res = self.keyword_check()
        self.assertEqual(res.status_code, 200, res.text)
        with self.Session() as s:
            saved = s.get(ScanHistory, self.scan_id).result_data["term_plan"]
        self.assertEqual([t["term"] for t in saved["terms"]], ["De-escalation", "Ticketing software"])
        self.assertEqual(len(saved["fingerprint"]), 64)

    def test_the_build_reuses_the_saved_plan_when_the_posting_and_roles_are_unchanged(self):
        self.keyword_check()
        saved = self.build()
        self.assertEqual([t["term"] for t in saved], ["De-escalation", "Ticketing software"])

    def test_a_build_without_a_keyword_step_plans_as_before(self):
        self.assertIsNone(self.build())

    def test_an_edited_posting_is_not_reused(self):
        self.keyword_check()
        self.assertIsNone(self.build(posting=POSTING + " Also: Salesforce."))

    def test_an_edited_role_is_not_reused(self):
        self.keyword_check()
        role = self.call("GET", "/experiences", self.a).json()[0]
        edit = {"title": "Shift Lead", "organization": "Hearthside Home Goods", "description": "Opened the store"}
        self.assertEqual(self.call("PUT", f"/experiences/{role['id']}", self.a, json=edit).status_code, 200)
        self.assertIsNone(self.build())

    def test_saving_a_skill_in_between_does_not_stop_reuse(self):
        self.keyword_check()
        self.assertEqual(self.call("POST", "/skills", self.a, json={"name": "Ticketing software"}).status_code, 200)
        self.assertIsNotNone(self.build())

    def test_the_keyword_check_without_a_scan_saves_nothing(self):
        self.assertEqual(self.keyword_check(scan_id=None).status_code, 200)
        with self.Session() as s:
            self.assertNotIn("term_plan", s.get(ScanHistory, self.scan_id).result_data)

    def test_another_persons_scan_id_is_refused_and_nothing_is_saved_there(self):
        self.onboard(self.b)
        res = self.keyword_check(who=self.b)
        self.assertEqual(res.status_code, 400, res.text)
        with self.Session() as s:
            self.assertNotIn("term_plan", s.get(ScanHistory, self.scan_id).result_data)


if __name__ == "__main__":
    unittest.main()
