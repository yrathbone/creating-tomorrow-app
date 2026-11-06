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


if __name__ == "__main__":
    unittest.main()
