"""Tests for the checked resume pipeline. No real AI calls: job_match._call_with_retry
is replaced with scripted answers.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -v
"""
import copy
import unittest
from unittest import mock

from career import job_match, term_pipeline
from career.job_match import JobMatchError
from career.term_pipeline import normalize, term_in_text

PROFILE = (
    "EXPERIENCE:\n- Treasury Technical Consultant at Bank of America\n"
    "  * Led executive training on API, FastPayments, and Fintech innovation.\n"
    "  * Directed contributions to RFP responses and business-case development.\n"
    "  * Acted as principal technical advisor to treasury and IT teams.\n"
)
POSTING = "Account Executive. Fintech, proposal development, technical expertise, pricing strategies."

BASE_RESUME = {
    "name": "Jane Doe", "contact": "Chicago | jane@example.com", "headline": "Treasury Technology Leader",
    "summary": "Treasury professional.",
    "skills": ["Payments: API Connectivity, ISO 20022"],
    "experience": [{"title": "Technical Consultant", "subtitle": "BofA", "bullets": ["Led integrations."]}],
    "education": ["MS IT"], "certifications": [],
}


def plan(*terms):
    return {"terms": [
        {"term": t, "importance": imp, "support": sup, "evidence": ev} for (t, imp, sup, ev) in terms
    ]}


class Matching(unittest.TestCase):
    def test_normalize_ignores_case_hyphens_and_plurals(self):
        self.assertEqual(normalize("Business-Case Development"), normalize("business cases development"))
        self.assertTrue(term_in_text("business cases", "Led business-case development"))
        self.assertTrue(term_in_text("APIs", "API connectivity"))
        self.assertTrue(term_in_text("Fintech", "FinTech innovation"))

    def test_no_partial_word_matches(self):
        self.assertFalse(term_in_text("API", "rapid growth"))
        self.assertFalse(term_in_text("bank", "banking"))

    def test_multi_word_term_inside_longer_phrase(self):
        self.assertTrue(term_in_text("financial technology", "Financial Technology (Fintech)"))


class Dedupe(unittest.TestCase):
    def test_repeated_skills_are_removed_across_groups(self):
        # Mirrors the real output that listed "Solution Architecture" and
        # "Integrations" twice.
        resume = dict(BASE_RESUME, skills=[
            "Sales: Consultative Selling, Pricing Strategies, Demonstrations",
            "Technical: Solution Architecture, Integrations, APIs, Solution Architecture, Integrations",
            "Industry: consultative selling, Financial Services, Pricing Strategy",
        ])
        out = term_pipeline.dedupe_skills(resume)["skills"]
        self.assertEqual(out[0], "Sales: Consultative Selling, Pricing Strategies, Demonstrations")
        self.assertEqual(out[1], "Technical: Solution Architecture, Integrations, APIs")
        self.assertEqual(out[2], "Industry: Financial Services")  # plural/case repeats dropped

    def test_commas_inside_parentheses_are_kept_together(self):
        resume = dict(BASE_RESUME, skills=["Tools: Data Analytics (Tableau, Power BI, SQL), CRM"])
        out = term_pipeline.dedupe_skills(resume)["skills"]
        self.assertEqual(out, ["Tools: Data Analytics (Tableau, Power BI, SQL), CRM"])

    def test_sentence_like_entries_are_dropped_but_keywords_stay(self):
        # Entries copied from a real output that were sentence fragments, not skills.
        resume = dict(BASE_RESUME, skills=[
            "Execution: Taking Ownership of Complex Initiatives, Working Across Multiple Functional Areas, "
            "Project Management, Product Education, Technology-Enabled Financial Solutions",
            "Technical: Selling or Supporting Complex Integrated Technology and Payment Solutions, APIs, "
            "ERP/TMS & Bank Connectivity (SWIFT, ISO 20022, ACH, APIs)",
        ])
        out = term_pipeline.dedupe_skills(resume)["skills"]
        self.assertEqual(out[0], "Execution: Project Management, Product Education, Technology-Enabled Financial Solutions")
        self.assertEqual(out[1], "Technical: APIs, ERP/TMS & Bank Connectivity (SWIFT, ISO 20022, ACH, APIs)")

    def test_leftover_and_or_prefixes_are_stripped(self):
        resume = dict(BASE_RESUME, skills=["Comms: Verbal, Written, and Customer Communication Skills, Strategies, and Best Practices"])
        out = term_pipeline.dedupe_skills(resume)["skills"]
        self.assertEqual(out, ["Comms: Verbal, Written, Customer Communication Skills"])

    def test_real_compound_skills_are_not_cut(self):
        resume = dict(BASE_RESUME, skills=[
            "Sales: Go-to-Market Playbook & Sales Enablement Development, Treasury & Cash Management Solutions, "
            "Articulate Business Value, Managing Multiple Priorities",
        ])
        out = term_pipeline.dedupe_skills(resume)["skills"]
        self.assertEqual(out, ["Sales: Go-to-Market Playbook & Sales Enablement Development, Treasury & Cash Management Solutions"])

    def test_semicolon_separated_skills_are_split_into_keywords(self):
        resume = dict(BASE_RESUME, skills=[
            "Core Capabilities: Analytical and Problem-Solving; Presentation Skills; CRM/Pipeline Management",
        ])
        out = term_pipeline.dedupe_skills(resume)["skills"]
        self.assertEqual(out, ["Core Capabilities: Analytical and Problem-Solving, Presentation Skills, CRM/Pipeline Management"])

    def test_line_left_empty_is_dropped(self):
        resume = dict(BASE_RESUME, skills=["A: APIs", "B: apis"])
        self.assertEqual(term_pipeline.dedupe_skills(resume)["skills"], ["A: APIs"])


class PlanGuards(unittest.TestCase):
    def test_sentence_fragments_are_dropped_from_the_plan(self):
        with mock.patch.object(job_match, "_call_with_retry", return_value=plan(
            ("Technical expertise", "required", "related", "technical advisor at BofA"),
            ("Translate complex technical concepts into clear business value", "required", "related", "advisor"),
        )):
            out = term_pipeline.plan_terms(PROFILE, "(none confirmed)", POSTING)
        self.assertEqual([t["term"] for t in out], ["Technical expertise"])

    def run_plan(self, ai_terms):
        with mock.patch.object(job_match, "_call_with_retry", return_value=ai_terms):
            return term_pipeline.plan_terms(PROFILE, "(none confirmed)", POSTING)

    def test_literal_match_is_forced_even_if_model_says_none(self):
        out = self.run_plan(plan(("Fintech", "required", "none", "")))
        self.assertEqual(out[0]["support"], "literal")

    def test_model_literal_claim_is_downgraded_when_not_in_profile(self):
        out = self.run_plan(plan(("Pricing strategies", "required", "literal", "pricing work at BofA")))
        self.assertEqual(out[0]["support"], "related")

    def test_related_without_evidence_becomes_none(self):
        out = self.run_plan(plan(("Pricing strategies", "required", "related", "")))
        self.assertEqual(out[0]["support"], "none")

    def test_duplicates_are_removed(self):
        out = self.run_plan(plan(("Fintech", "required", "literal", ""), ("fintech", "preferred", "literal", "")))
        self.assertEqual(len(out), 1)


class Pipeline(unittest.TestCase):
    def scripted(self, plan_answer, built, revised=None, plan_error=False, revise_error=False):
        calls = []

        def fake(label, system_prompt, user_prompt, tool, extract):
            calls.append((label, user_prompt))
            if label == "career_term_plan":
                if plan_error:
                    raise JobMatchError("plan failed")
                return plan_answer
            if label == "career_job_build_resume":
                return {"resume_data": copy.deepcopy(built), "role_selection": []}
            if label == "career_term_revise":
                if revise_error:
                    raise JobMatchError("revise failed")
                return {"resume_data": revised}
            raise AssertionError(label)

        return fake, calls

    def test_missing_supported_term_is_added_by_the_fixup_and_reported(self):
        fixed = copy.deepcopy(BASE_RESUME)
        fixed["skills"] = ["Payments: API Connectivity, ISO 20022, Fintech", "Sales: Proposal Development"]
        answer = plan(
            ("Fintech", "required", "literal", ""),
            ("Proposal development", "required", "related", "RFP responses at BofA"),
            ("Pricing strategies", "required", "none", ""),
        )
        fake, calls = self.scripted(answer, BASE_RESUME, revised=fixed)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Jane Doe", "Chicago | jane@example.com")

        self.assertEqual([c[0] for c in calls], ["career_term_plan", "career_job_build_resume", "career_term_revise"])
        status = {r["term"]: r["status"] for r in result["term_report"]}
        self.assertEqual(status, {"Fintech": "on_resume", "Proposal development": "on_resume", "Pricing strategies": "not_in_profile"})
        self.assertIn("Fintech", " ".join(result["resume_data"]["skills"]))

    def test_build_prompt_carries_include_and_exclude_lists(self):
        answer = plan(("Fintech", "required", "literal", ""), ("Pricing strategies", "required", "none", ""))
        built = copy.deepcopy(BASE_RESUME)
        built["skills"] = ["Payments: Fintech"]
        fake, calls = self.scripted(answer, built)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Jane Doe", "x@y.com")
        build_prompt = dict(calls)["career_job_build_resume"]
        include_part, exclude_part = build_prompt.split("POSTING TERMS WITH NO EVIDENCE")
        self.assertIn("- Fintech", include_part)
        self.assertNotIn("Pricing strategies", include_part.split("POSTING TERMS TO INCLUDE")[1])
        self.assertIn("- Pricing strategies", exclude_part)

    def test_no_fixup_call_when_everything_is_already_placed(self):
        built = copy.deepcopy(BASE_RESUME)
        built["skills"] = ["Payments: Fintech"]
        fake, calls = self.scripted(plan(("Fintech", "required", "literal", "")), built)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Jane Doe", "x@y.com")
        self.assertEqual([c[0] for c in calls], ["career_term_plan", "career_job_build_resume"])
        self.assertEqual(result["term_report"][0]["status"], "on_resume")

    def test_malformed_fixup_keeps_the_original_and_marks_not_placed(self):
        broken = copy.deepcopy(BASE_RESUME)
        broken["experience"] = []  # lost every role: must be rejected
        fake, _ = self.scripted(plan(("Fintech", "required", "literal", "")), BASE_RESUME, revised=broken)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Jane Doe", "x@y.com")
        self.assertEqual(len(result["resume_data"]["experience"]), 1)
        self.assertEqual(result["term_report"][0]["status"], "not_placed")

    def test_fixup_failure_keeps_the_original(self):
        fake, _ = self.scripted(plan(("Fintech", "required", "literal", "")), BASE_RESUME, revise_error=True)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Jane Doe", "x@y.com")
        self.assertEqual(result["term_report"][0]["status"], "not_placed")

    def test_planning_failure_falls_back_to_the_plain_build(self):
        fake, calls = self.scripted(None, BASE_RESUME, plan_error=True)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Jane Doe", "x@y.com")
        self.assertEqual([c[0] for c in calls], ["career_term_plan", "career_job_build_resume"])
        self.assertEqual(result["term_report"], [])
        self.assertIn("no list provided", dict(calls)["career_job_build_resume"])


class KeywordCheck(unittest.TestCase):
    def test_only_terms_missing_from_the_profile_are_returned_required_first(self):
        answer = plan(
            ("Fintech", "required", "literal", ""),
            ("Pricing strategies", "preferred", "none", ""),
            ("Technical expertise", "required", "related", "technical advisor at BofA"),
            ("Sales cycle", "required", "none", ""),
        )
        with mock.patch.object(job_match, "_call_with_retry", return_value=answer):
            out = term_pipeline.keyword_check(PROFILE, [], POSTING)
        self.assertEqual([t["term"] for t in out["terms"]], ["Technical expertise", "Sales cycle", "Pricing strategies"])
        self.assertEqual(out["already_covered"], 1)

    def test_a_term_confirmed_as_a_fact_counts_as_covered(self):
        facts = [{"category": "Sales cycle", "bullet_text": "Owned the sales cycle end to end."}]
        with mock.patch.object(job_match, "_call_with_retry", return_value=plan(("Sales cycle", "required", "none", ""))):
            out = term_pipeline.keyword_check(PROFILE, facts, POSTING)
        self.assertEqual(out["terms"], [])
        self.assertEqual(out["already_covered"], 1)


class SkillTidy(unittest.TestCase):
    SKILLS = [
        {"id": 1, "name": "Sales Enablement/Training Content Creation", "source_text": "Created pitch decks."},
        {"id": 2, "name": "Fintech", "source_text": None},
        {"id": 3, "name": "Contract Negotiation & Pricing Authority", "source_text": "Negotiated terms."},
        {"id": 4, "name": "Client Escalation/Crisis Management at Scale", "source_text": ""},
    ]

    def test_only_long_names_are_candidates(self):
        self.assertEqual([s["id"] for s in term_pipeline.tidy_candidates(self.SKILLS)], [1, 3, 4])

    def test_suggestions_are_guarded(self):
        answer = {"skills": [
            {"id": 1, "keyword": "Sales Enablement"},
            {"id": 3, "keyword": "Negotiating contract terms with clients"},  # too long
            {"id": 4, "keyword": "Managing client escalations"},  # verb-first
            {"id": 99, "keyword": "Not Mine"},  # unknown id
        ]}
        with mock.patch.object(job_match, "_call_with_retry", return_value=answer):
            out = term_pipeline.suggest_skill_keywords(term_pipeline.tidy_candidates(self.SKILLS))
        self.assertEqual(out, {1: "Sales Enablement"})


if __name__ == "__main__":
    unittest.main()
