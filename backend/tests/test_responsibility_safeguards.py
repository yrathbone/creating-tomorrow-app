"""Priority 1, PR 4: responsibility safeguards. Stronger verbs (performed, supervised, guided, mentored, coordinated...), a check per activity
and not per profile, evidence that argues against itself, and one card for contained duplicates. Fictional project-manager benchmark, saved data, no AI.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest
from unittest import mock

from career import job_match, resume_quality, term_pipeline

EVIDENCE = """Senior Project Manager, Northwind Payments
- Managed the client onboarding budget of 40 thousand dollars
- Assisted with file testing for client connectivity go-lives
- Coordinated with project managers and engineers on data migration cutovers
- Supported data mapping reviews with the integration team"""


def flags(sentence, evidence=EVIDENCE):
    return resume_quality.verb_upgrades({"summary": "", "experience": [{"title": "PM", "bullets": [sentence]}]}, evidence)


class A_StrongerVerbsAreFlagged(unittest.TestCase):
    def test_performed_is_flagged_when_the_evidence_only_says_assisted(self):
        self.assertEqual([f["written"] for f in flags("Performed file testing for client connectivity go-lives.")], ["performed"])

    def test_supervised_guided_and_mentored_are_flagged_when_the_evidence_says_coordinated_with(self):
        for verb in ("Supervised", "Guided", "Mentored"):
            out = flags(f"{verb} project managers and engineers on data migration cutovers.")
            self.assertEqual([f["written"] for f in out], [verb.lower()], verb)

    def test_the_verb_the_candidate_used_is_not_flagged(self):
        self.assertEqual(flags("Assisted with file testing for client connectivity go-lives."), [])
        self.assertEqual(flags("Coordinated with project managers and engineers on data migration cutovers."), [])


class B_TheCheckIsPerActivityNotPerProfile(unittest.TestCase):
    def test_managed_is_flagged_for_the_activity_the_candidate_only_assisted_with(self):
        # "Managed" IS in the evidence (the budget), but for file testing the candidate only assisted
        out = flags("Managed file testing for client connectivity go-lives.")
        self.assertEqual([(f["written"], f["evidence_verb"]) for f in out], [("managed", "assisted")])

    def test_managed_stays_for_the_activity_the_candidate_really_managed(self):
        self.assertEqual(flags("Managed the client onboarding budget of 40 thousand dollars."), [])

    def test_a_sentence_about_an_activity_the_evidence_never_describes_is_left_alone(self):
        self.assertEqual(flags("Managed vendor contracts for the regional office."), [])

    def test_a_flagged_activity_is_restored_to_the_candidates_own_sentence_or_held_never_kept_as_written(self):
        resume = {"summary": "", "experience": [{"title": "PM", "bullets": ["Managed file testing for client connectivity go-lives."]}]}
        fixed, restored, held = resume_quality.resolve_verb_upgrades(resume, EVIDENCE)
        bullets = fixed["experience"][0]["bullets"]
        self.assertNotIn("Managed file testing for client connectivity go-lives.", bullets)
        self.assertTrue(restored or held)


PROFILE = EVIDENCE


def term(name, importance, support, evidence=""):
    return {"term": name, "importance": importance, "kind": "skill", "support": support, "evidence": evidence}


def check(plan):
    with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": plan}):
        return term_pipeline.keyword_check(PROFILE, [], "posting text")


class C_EvidenceThatArguesAgainstItselfIsNotCovered(unittest.TestCase):
    HEDGED = ("Candidate has not held a customer success title, but complaint handling is adjacent; however this is a different specialized role. "
              "Marking related.")

    def test_a_related_term_whose_own_note_says_different_or_adjacent_becomes_a_question(self):
        out = check([term("customer success", "required", "related", self.HEDGED)])
        self.assertEqual(out["covered_related"], [])
        self.assertEqual([(t["term"], t["support"]) for t in out["terms"]], [("customer success", "transferable")])

    def test_a_plain_related_note_is_still_covered(self):
        out = check([term("client implementation", "required", "related", "Managed client connectivity projects")])
        self.assertEqual([t["term"] for t in out["covered_related"]], ["client implementation"])
        self.assertEqual(out["terms"], [])

    def test_the_build_plan_also_stops_calling_it_related(self):
        with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": [term("customer success", "required", "related", self.HEDGED)]}):
            terms = term_pipeline.plan_terms(PROFILE, "(none confirmed)", "posting text")
        self.assertEqual(terms[0]["support"], "transferable")


class D_ContainedDuplicatesAreOneCard(unittest.TestCase):
    def test_saas_and_saas_experience_are_one_question_with_the_stronger_importance(self):
        out = check([term("SaaS experience", "preferred", "none"), term("SaaS", "required", "none")])
        self.assertEqual([(t["term"], t["importance"]) for t in out["terms"]], [("SaaS experience", "required")])

    def test_different_terms_that_share_one_word_are_both_kept(self):
        out = check([term("written communication", "required", "none"), term("communication skills", "required", "none")])
        self.assertEqual(len(out["terms"]), 2)

    def test_a_term_is_never_dropped_into_a_covered_one(self):
        out = check([term("Project Management", "required", "literal"), term("Project Management Office", "required", "none")])
        self.assertEqual([t["term"] for t in out["terms"]], ["Project Management Office"])


class E_LiveFindingHedgedPhrasingAndTheTitleCore(unittest.TestCase):
    """Found in the 2026-11-06 live full-flow check on a fictional account: the planner wrote "though not SaaS customer success specifically" and
    "though not specifically scheduling customer calls" as the reason for "related", the old phrases did not match, and "Customer Success" and
    "Scheduling Calls" were printed in the Skills of a resume for a Customer Success Associate role."""
    CUSTOMER_SUCCESS = ("Candidate's customer-facing roles (Sales Associate, Shift Lead handling returns/complaints) show account/relationship-style "
                        "customer work, though not SaaS customer success specifically.")
    SCHEDULING_CALLS = "Shift Lead: 'Scheduled 6 associates each week' shows scheduling experience, though not specifically scheduling customer calls."
    POSTING = "Customer Success Associate (SaaS)\nRun onboarding calls with new customers and resolve cases."

    def plan(self, terms, posting=None):
        with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": terms}):
            return {t["term"]: t["support"] for t in term_pipeline.plan_terms(PROFILE, "(none confirmed)", posting or self.POSTING)}

    def test_though_not_and_not_specifically_are_hedges(self):
        out = self.plan([term("scheduling calls", "required", "related", self.SCHEDULING_CALLS)])
        self.assertEqual(out["scheduling calls"], "transferable")

    def test_the_other_new_hedge_phrasings(self):
        for note in ("Handled complaints but not onboarding.", "Is only loosely connected to sales.", "Covers it, not exactly, through retail work.",
                     "Did similar work, although not directly for customers."):
            self.assertEqual(self.plan([term("account management", "required", "related", note)])["account management"], "transferable", note)

    def test_a_plain_reason_is_still_related(self):
        out = self.plan([term("phone communication", "mentioned", "related", "Call Centre Agent: 'Took inbound customer orders by phone for 4 months.'")])
        self.assertEqual(out["phone communication"], "related")

    def test_a_term_that_is_the_heart_of_the_title_is_never_related_even_with_a_clean_reason(self):
        out = self.plan([term("customer success", "required", "related", "Handles returns and builds customer relationships")])
        self.assertEqual(out["customer success"], "transferable")

    def test_the_title_core_rule_does_not_touch_other_terms_or_literal_evidence(self):
        out = self.plan([term("customer service", "required", "related", "Handles customer questions"), term("team coordination", "required", "related", "Coordinated with project managers and engineers")])
        self.assertEqual((out["customer service"], out["team coordination"]), ("related", "related"))  # one word or not in the title: unchanged
        literal = "Customer Success Associate role at Acme\n- Customer success"
        with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": [term("customer success", "required", "literal", "")]}):
            terms = term_pipeline.plan_terms(literal, "(none confirmed)", self.POSTING)
        self.assertEqual(terms[0]["support"], "literal")

    def test_the_keyword_check_asks_instead_of_listing_them_as_backed(self):
        plan = [term("customer success", "required", "related", self.CUSTOMER_SUCCESS), term("scheduling calls", "required", "related", self.SCHEDULING_CALLS)]
        with mock.patch.object(job_match, "_call_with_retry", return_value={"terms": plan}):
            out = term_pipeline.keyword_check(PROFILE, [], self.POSTING)
        self.assertEqual(out["covered_related"], [])
        self.assertEqual(sorted(t["term"] for t in out["terms"]), ["customer success", "scheduling calls"])


if __name__ == "__main__":
    unittest.main()
