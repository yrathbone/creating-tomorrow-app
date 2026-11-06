"""Priority 1, PR 1: the keyword check asks only about real gaps. Terms the profile already backs (the exact wording, or the same activity under other
words with named evidence) are listed with that evidence and never asked. Fictional benchmark: a project manager in client connectivity.
Saved data, a stand-in planner, no AI.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest
from unittest import mock

from career import job_match, term_pipeline

PROFILE = """Senior Project Manager, Northwind Payments (2019-2025)
  * Managed client connectivity projects for banking customers across 4 regions
  * Coordinated with project managers and engineers on data migration cutovers
  * Assisted with file testing for client connectivity go-lives; documented test results
  * Reported weekly status to stakeholders
Business Analyst, Contoso Systems (2014-2019)
  * Gathered requirements for payment file formats (ISO 20022, SWIFT)
Skills: Project Management, Stakeholder Management, Client Onboarding, Agile, SQL, ISO 20022, SWIFT, Risk Management"""


def term(name, importance, support, evidence="", kind="skill"):
    return {"term": name, "importance": importance, "kind": kind, "support": support, "evidence": evidence}


PLAN = (
    [term(x, "required", "literal") for x in ["Project Management", "Stakeholder Management", "Agile", "Risk Management", "SQL", "ISO 20022", "SWIFT", "Client Onboarding"]]
    + [
        term("Client implementation", "required", "related", "Managed client connectivity projects"),
        term("Cross-functional teams", "required", "related", "Coordinated with project managers and engineers"),
        term("Data migration", "preferred", "related", "Coordinated data migration cutovers"),
        term("Testing and validation", "preferred", "related", "Assisted with file testing"),
        term("Status reporting", "preferred", "related", "Reported weekly status to stakeholders"),
        term("Requirements gathering", "preferred", "related", "Gathered requirements for payment file formats"),
        term("Data mapping", "preferred", "transferable", "Assisted with file testing for client go-lives"),
        term("Change management", "required", "none"),
        term("PMP", "required", "none"),
        term("Vendor management", "preferred", "none"),
        term("delivery in regulated environments", "mentioned", "none", kind="phrase"),
    ]
)


def check(plan=PLAN, facts=None):
    with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": plan}):
        return term_pipeline.keyword_check(PROFILE, facts or [], "posting text")


class A_OnlyRealGapsBecomeQuestions(unittest.TestCase):
    def test_the_benchmark_asks_four_questions_not_a_dozen(self):
        out = check()
        asked = [t["term"] for t in out["terms"]]
        self.assertEqual(asked, ["Change management", "PMP", "Data mapping", "Vendor management"])  # required first, then the transferable one
        # the code guard turns "Data migration" into an exact match (the profile literally says it), so 14 terms in all need no answer
        self.assertEqual(len(out["covered_exact"]) + len(out["covered_related"]), 14)
        self.assertIn("Data migration", [t["term"] for t in out["covered_exact"]])

    def test_related_terms_with_evidence_are_listed_with_that_evidence_and_never_asked(self):
        out = check()
        self.assertNotIn("Client implementation", [t["term"] for t in out["terms"]])
        related = {t["term"]: t["evidence"] for t in out["covered_related"]}
        self.assertEqual(related["Client implementation"], "Managed client connectivity projects")
        self.assertEqual(related["Status reporting"], "Reported weekly status to stakeholders")

    def test_a_different_activity_is_still_a_question_not_a_covered_term(self):
        out = check()
        data_mapping = [t for t in out["terms"] if t["term"] == "Data mapping"][0]
        self.assertEqual(data_mapping["support"], "transferable")
        self.assertNotIn("Data mapping", [t["term"] for t in out["covered_related"]])

    def test_a_term_with_no_evidence_is_never_called_covered(self):
        out = check()
        covered = {t["term"] for t in out["covered_exact"]} | {t["term"] for t in out["covered_related"]}
        for gap in ("Change management", "PMP", "Vendor management", "Data mapping"):
            self.assertNotIn(gap, covered)

    def test_the_count_is_exact_terms_plus_related_terms_plus_context_phrases(self):
        out = check()
        self.assertEqual(out["already_covered"], 14 + 1)


class B_NothingIsPromotedOrChanged(unittest.TestCase):
    def test_related_stays_related_in_the_plan_the_build_uses(self):
        with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": PLAN}):
            terms = term_pipeline.plan_terms(PROFILE, "(none confirmed)", "posting text")
        by_name = {t["term"]: t["support"] for t in terms}
        self.assertEqual(by_name["Client implementation"], "related")
        self.assertEqual(by_name["Change management"], "none")

    def test_a_related_term_with_no_evidence_is_not_covered(self):
        plan = [term("Client implementation", "required", "related", "")]  # the planner code downgrades it to none
        out = check(plan)
        self.assertEqual([t["term"] for t in out["terms"]], ["Client implementation"])
        self.assertEqual(out["covered_related"], [])

    def test_a_confirmed_fact_still_moves_a_term_to_exact(self):
        facts = [{"category": "Change management", "bullet_text": "Led change management for a client cutover."}]
        out = check(facts=facts)
        self.assertIn("Change management", [t["term"] for t in out["covered_exact"]])
        self.assertNotIn("Change management", [t["term"] for t in out["terms"]])

    def test_the_response_keeps_the_old_keys_the_page_reads(self):
        out = check()
        for key in ("terms", "already_covered"):
            self.assertIn(key, out)


def group_term(name, support="none", evidence="", group="project-management-credential", equiv=True, importance="required"):
    return {**term(name, importance, support, evidence), "alternatives_group": group, "accepts_equivalent_experience": equiv}


class C_AlternativesAreOneRequirement(unittest.TestCase):
    def test_a_group_with_no_evidence_is_one_question_naming_every_alternative(self):
        out = check([group_term("PMP"), group_term("PRINCE2")])
        self.assertEqual(len(out["terms"]), 1)
        q = out["terms"][0]
        self.assertEqual((q["term"], q["alternatives"], q["importance"], q["support"]), ("PMP or PRINCE2", ["PMP", "PRINCE2"], "required", "none"))
        self.assertTrue(q["accepts_equivalent_experience"])
        self.assertEqual(out["alternatives_met"], [])

    def test_one_backed_member_meets_the_group_and_the_others_are_not_asked(self):
        out = check([group_term("PMP"), group_term("PRINCE2", "related", "Managed client connectivity projects")])
        self.assertEqual(out["terms"], [])
        met = out["alternatives_met"][0]
        self.assertEqual((met["terms"], met["met_by"], met["evidence"]), (["PMP", "PRINCE2"], "PRINCE2", "Managed client connectivity projects"))

    def test_a_literal_member_meets_the_group_without_evidence_text(self):
        out = check([group_term("PMP"), group_term("Risk Management", "literal")])
        self.assertEqual(out["terms"], [])
        self.assertEqual(out["alternatives_met"][0]["met_by"], "Risk Management")
        self.assertEqual(out["alternatives_met"][0]["evidence"], "")

    def test_a_group_is_never_called_met_without_a_member_that_has_evidence(self):
        out = check([group_term("PMP"), group_term("PRINCE2", "related", "")])  # related with no evidence is downgraded to none
        self.assertEqual(out["alternatives_met"], [])
        self.assertEqual(len(out["terms"]), 1)

    def test_a_transferable_member_keeps_the_group_question_marked_transferable(self):
        out = check([group_term("PMP"), group_term("PRINCE2", "transferable", "Assisted with file testing")])
        self.assertEqual((out["terms"][0]["support"], out["terms"][0]["evidence"]), ("transferable", "Assisted with file testing"))

    def test_a_lone_label_is_an_ordinary_requirement(self):
        out = check([group_term("PMP")])
        self.assertEqual([t["term"] for t in out["terms"]], ["PMP"])
        self.assertNotIn("alternatives", out["terms"][0])

    def test_the_build_plan_is_unchanged_so_nothing_is_promoted(self):
        with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": [group_term("PMP"), group_term("PRINCE2", "related", "Managed client connectivity projects")]}):
            terms = term_pipeline.plan_terms(PROFILE, "(none confirmed)", "posting text")
        self.assertEqual({t["term"]: t["support"] for t in terms}, {"PMP": "none", "PRINCE2": "related"})

    def test_the_planner_asks_for_the_group_fields_and_says_grouping_never_changes_evidence(self):
        props = term_pipeline.PLAN_TOOL["input_schema"]["properties"]["terms"]["items"]["properties"]
        self.assertIn("alternatives_group", props)
        self.assertIn("accepts_equivalent_experience", props)
        self.assertIn("Grouping never changes the evidence judgement", term_pipeline.PLAN_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
