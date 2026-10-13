"""Truth and readability checks on a finished resume (career/resume_quality.py) and the one targeted fix pass that uses them
(term_pipeline.improve_readability). No real AI calls: job_match._call_with_retry is scripted.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -v
"""
import copy
import unittest
from unittest import mock

from career import job_match, resume_quality, term_pipeline
from career.term_pipeline import term_in_text

EVIDENCE = (
    "EXPERIENCE:\n- VP, Treasury Technical Consultant at Bank of America 2021 - 2025\n"
    "  * Led end-to-end delivery of 400+ enterprise treasury integrations.\n"
    "  * Managed a portfolio of 40+ corporate accounts above $500MM in annual revenue.\n"
    "  * Piloted product launches including Zelle and PayPal with SAP and Kyriba clients.\n"
    "- Product Consultant at Bank of America since 2015\n"
)


def resume(summary="Treasury professional.", bullets=("Led integrations.",), headline="Treasury Technology Leader"):
    return {
        "name": "Jane Doe", "contact": "x", "headline": headline, "summary": summary, "skills": ["Payments: APIs"],
        "experience": [{"title": "Consultant", "subtitle": "BofA", "bullets": list(bullets)}],
        "education": ["MS IT"], "certifications": [],
    }


def issues(res, terms=(), today=2026):
    return resume_quality.find_issues(res, EVIDENCE, list(terms), term_in_text, "", today_year=today)


def problems(res, **kw):
    return [i["problem"] for i in issues(res, **kw)]


class TruthChecks(unittest.TestCase):
    def test_a_clean_resume_has_no_problems(self):
        res = resume("Treasury consultant with 10+ years in payments. Led 400+ integrations for SAP clients.",
                     ["Managed a portfolio of 40+ corporate accounts above $500MM in annual revenue."])
        self.assertEqual(problems(res), [])

    def test_an_invented_figure_is_flagged(self):
        res = resume(bullets=["Grew revenue by 35% across 12 accounts."])
        found = problems(res)
        self.assertTrue(any('"35"' in p for p in found), found)
        self.assertTrue(any('"12"' in p for p in found), found)

    def test_figures_written_differently_are_still_recognised(self):
        res = resume(bullets=["Managed 40+ accounts above $500MM and delivered 400+ integrations."])
        self.assertEqual(problems(res), [])

    def test_years_of_experience_are_allowed_up_to_the_span_in_the_profile_and_no_further(self):
        self.assertEqual(problems(resume("Treasury professional with 11+ years of experience.")), [])  # 2026 - 2015 = 11
        self.assertTrue(any('"15"' in p for p in problems(resume("Treasury professional with 15+ years of experience."))))

    def test_a_name_that_is_not_in_the_profile_is_flagged_but_a_clause_start_is_not(self):
        res = resume(bullets=["Led integrations for Salesforce and SAP clients; Trusted advisor to executives."])
        found = problems(res)
        self.assertEqual(len(found), 1)
        self.assertIn("Salesforce", found[0])

    def test_a_supported_posting_term_may_be_used(self):
        res = resume(bullets=["Led integrations with Fintech partners."])
        self.assertTrue(problems(res))
        res_ok = resume_quality.find_issues(res, EVIDENCE, [], term_in_text, "Fintech literal", today_year=2026)
        self.assertEqual(res_ok, [])

    def test_the_headline_is_only_checked_for_figures(self):
        self.assertEqual(problems(resume(headline="Enterprise Client Advisory | Treasury Solutions")), [])
        self.assertTrue(problems(resume(headline="Top 5 Treasury Leader")))


class ReadabilityChecks(unittest.TestCase):
    def test_long_sentences_and_bullets_are_flagged(self):
        long_sentence = "Treasury professional " + "who delivers value " * 8 + "to clients."
        found = problems(resume(summary=long_sentence, bullets=["Led " + "integrations for treasury clients and " * 7 + "teams."]))
        self.assertTrue(any("summary sentence" in p for p in found), found)
        self.assertTrue(any("this bullet is" in p for p in found), found)

    def test_a_summary_over_four_sentences_is_flagged(self):
        self.assertTrue(any("sentences" in p for p in problems(resume(summary="One. Two. Three. Four. Five."))))

    def test_keyword_stuffing_is_flagged(self):
        terms = ["technical sales", "solutions consulting", "solution architecture", "payments"]
        res = resume(summary="Experience in technical sales, solutions consulting, solution architecture and payments.")
        self.assertTrue(any("keywords are packed" in p for p in problems(res, terms=terms)))
        self.assertEqual(problems(resume(summary="Experience in technical sales and payments."), terms=terms), [])

    def test_a_dash_run_on_and_a_thrice_repeated_word_are_flagged(self):
        self.assertTrue(any("dashes" in p for p in problems(resume(summary="Guided clients—from discovery to launch—with care."))))
        self.assertTrue(any("repeated three times" in p for p in problems(resume(bullets=["Integration of integrations for integration teams."]))))


class FixPass(unittest.TestCase):
    TERMS = [{"term": "technical sales", "kind": "skill", "importance": "required", "support": "literal", "evidence": ""}]

    def messy(self):
        return resume("Treasury professional in technical sales.", ["Led integrations and grew revenue by 35% for SAP clients."])

    def run_fix(self, revised, base=None):
        calls = []

        def fake(label, system_prompt, user_prompt, tool, extract):
            calls.append((label, user_prompt))
            return {"resume_data": copy.deepcopy(revised)}

        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            out, info = term_pipeline.improve_readability(base or self.messy(), EVIDENCE, copy.deepcopy(self.TERMS))
        return out, info, calls

    def test_no_ai_call_when_the_resume_is_clean(self):
        clean = resume("Treasury professional in technical sales.", ["Led 400+ integrations."])
        out, info, calls = self.run_fix(clean, base=clean)
        self.assertEqual(calls, [])
        self.assertEqual(info, {"found": 0, "remaining": 0, "edited": False})

    def test_a_good_edit_is_accepted_and_the_prompt_carries_the_problem_and_the_evidence(self):
        fixed = self.messy()
        fixed["experience"][0]["bullets"] = ["Led integrations for SAP clients."]
        out, info, calls = self.run_fix(fixed)
        self.assertTrue(info["edited"])
        self.assertEqual(out["experience"][0]["bullets"], ["Led integrations for SAP clients."])
        self.assertEqual([c[0] for c in calls], ["career_readability_fix"])
        self.assertIn('the figure "35"', calls[0][1])
        self.assertIn("Led end-to-end delivery of 400+", calls[0][1])
        self.assertIn("- technical sales", calls[0][1])

    def test_an_edit_that_loses_a_keyword_is_rejected(self):
        fixed = self.messy()
        fixed["summary"] = "Treasury professional."
        fixed["experience"][0]["bullets"] = ["Led integrations for SAP clients."]
        out, info, _ = self.run_fix(fixed)
        self.assertFalse(info["edited"])
        self.assertEqual(out, self.messy())

    def test_an_edit_that_adds_a_new_fact_is_rejected(self):
        fixed = self.messy()
        fixed["experience"][0]["bullets"] = ["Led integrations and cut costs by 20% for Oracle clients."]
        out, info, _ = self.run_fix(fixed)
        self.assertFalse(info["edited"])
        self.assertEqual(out, self.messy())

    def test_an_edit_that_drops_a_bullet_is_rejected(self):
        fixed = self.messy()
        fixed["experience"][0]["bullets"] = []
        out, info, _ = self.run_fix(fixed)
        self.assertFalse(info["edited"])

    def test_a_failing_fix_call_keeps_the_original_and_never_breaks_the_build(self):
        with mock.patch.object(job_match, "_call_with_retry", side_effect=job_match.JobMatchError("boom")):
            out, info = term_pipeline.improve_readability(self.messy(), EVIDENCE, copy.deepcopy(self.TERMS))
        self.assertEqual(out, self.messy())
        self.assertFalse(info["edited"])


class WholeBuild(unittest.TestCase):
    """Through build_checked_resume: the quality pass runs after the keyword work, with confirmed facts counted as evidence."""

    PROFILE = "EXPERIENCE:\n- Treasury Technical Consultant at Bank of America 2021 - 2025\n  * Led executive training on API and Fintech innovation.\n"

    def scripted(self, built, fixed):
        calls = []

        def fake(label, system_prompt, user_prompt, tool, extract):
            calls.append(label)
            if label == "career_term_plan":
                return {"terms": [{"term": "Fintech", "importance": "required", "support": "literal", "evidence": ""}]}
            if label == "career_job_build_resume":
                return {"resume_data": copy.deepcopy(built), "role_selection": []}
            if label == "career_readability_fix":
                return {"resume_data": copy.deepcopy(fixed)}
            raise AssertionError(label)

        return fake, calls

    def base(self, bullet):
        res = resume("Treasury professional.", [bullet])
        res["skills"] = ["Payments: Fintech"]
        return res

    def test_a_messy_build_is_fixed_and_the_keyword_stays(self):
        built = self.base("Led executive training on Fintech and grew revenue by 35%.")
        fixed = self.base("Led executive training on Fintech innovation.")
        fake, calls = self.scripted(built, fixed)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(self.PROFILE, "Fintech role", [], "Jane Doe", "x@y.com")
        self.assertEqual(calls, ["career_term_plan", "career_job_build_resume", "career_readability_fix"])
        self.assertEqual(result["resume_data"]["experience"][0]["bullets"], ["Led executive training on Fintech innovation."])
        self.assertEqual(result["quality"], {"found": 1, "remaining": 0, "edited": True})
        self.assertEqual(result["term_report"][0]["status"], "on_resume")

    def test_a_confirmed_fact_counts_as_evidence_so_its_figure_is_not_flagged(self):
        built = self.base("Led executive training on Fintech and managed 40 accounts.")
        facts = [{"category": "Accounts", "bullet_text": "Managed 40 corporate accounts."}]
        fake, calls = self.scripted(built, built)
        with mock.patch.object(job_match, "_call_with_retry", side_effect=fake):
            result = term_pipeline.build_checked_resume(self.PROFILE, "Fintech role", facts, "Jane Doe", "x@y.com")
        self.assertEqual(calls, ["career_term_plan", "career_job_build_resume"])
        self.assertEqual(result["quality"]["found"], 0)


if __name__ == "__main__":
    unittest.main()
