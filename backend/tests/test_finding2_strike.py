"""Finding 2, narrow additions: the last-resort strike of unsupported sentences, and the saved truth review.

After the edit pass (which can be unavailable or incomplete), any sentence that still states a qualification the evidence does not
establish is removed by plain code, so a flagged claim cannot reach the saved or downloaded resume. Fictional data only.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import io
import os
import unittest
from unittest import mock

from docx import Document

import abuse_guard
import resume_builder as rb
from career import term_pipeline
from tests.test_finding2_truthfulness import (
    DANIEL_AFTER_EDIT, DANIEL_BEFORE, DANIEL_FACT, DANIEL_HISTORY, DANIEL_PLAN, DANIEL_PROFILE, SEARS_BAD, SEARS_GOOD, SEARS_PLAN,
    SEARS_POSTING, SEARS_PROFILE, prose, run, skills_text,
)
from tests.test_ownership import OwnershipTestCase

UNSUPPORTED = ["video editing", "subject matter experts", "e-learning modules"]


class StrikeUnsupportedClaims(unittest.TestCase):
    def test_only_the_offending_sentence_goes_and_the_rest_of_the_bullet_stays(self):
        resume = copy.deepcopy(DANIEL_BEFORE)
        resume["summary"] = DANIEL_AFTER_EDIT["summary"]  # a clean summary, so only the bullet is under test
        resume["experience"][0]["bullets"] = ["Recorded 60 short lesson videos. Applied video editing skills to polish them."]
        out, struck = term_pipeline.strike_unsupported_claims(resume, UNSUPPORTED)
        self.assertEqual(out["experience"][0]["bullets"], ["Recorded 60 short lesson videos."])
        self.assertEqual([s["text"] for s in struck], ["Applied video editing skills to polish them."])

    def test_a_bullet_with_nothing_left_is_dropped_and_nothing_is_substituted(self):
        out, struck = term_pipeline.strike_unsupported_claims(copy.deepcopy(DANIEL_BEFORE), UNSUPPORTED)
        bullets = out["experience"][0]["bullets"]
        self.assertEqual(len(bullets), 3)  # the e-learning bullet and the "subject matter resource" bullet are gone, not rewritten
        self.assertNotIn("e-learning modules", " ".join(bullets).lower())
        self.assertNotIn("video editing", " ".join(bullets).lower())
        self.assertNotIn("subject matter", " ".join(bullets).lower())  # a paraphrase of "subject matter experts" is caught too
        self.assertEqual(len(struck), 6)  # three summary sentences, two e-learning sentences and the "subject matter resource" sentence
        # known cost: that last sentence also held the true "mentored two student teachers", which goes with it
        self.assertNotIn("mentored two student teachers", " ".join(bullets).lower())

    def test_summary_sentences_and_headline_phrases_are_struck_too(self):
        out, _ = term_pipeline.strike_unsupported_claims(copy.deepcopy(DANIEL_BEFORE), UNSUPPORTED)
        self.assertNotIn("subject matter experts", out["summary"].lower())
        self.assertNotIn("video editing", out["summary"].lower())
        self.assertIn("Educator with over 10 years of teaching experience", out["summary"])  # a clean sentence stays
        # known cost: a sentence is struck whole, so supported facts that share a sentence with an unsupported claim go with it
        self.assertNotIn("project-based curriculum", out["summary"])
        headline = dict(copy.deepcopy(DANIEL_BEFORE), headline="Instructional Design | Video Editing | Curriculum")
        self.assertEqual(term_pipeline.strike_unsupported_claims(headline, UNSUPPORTED)[0]["headline"], "Instructional Design | Curriculum")

    def test_nothing_is_changed_when_nothing_is_flagged_or_when_there_is_no_plan(self):
        clean = copy.deepcopy(DANIEL_AFTER_EDIT)
        self.assertEqual(term_pipeline.strike_unsupported_claims(clean, UNSUPPORTED), (clean, []))
        self.assertEqual(term_pipeline.strike_unsupported_claims(copy.deepcopy(DANIEL_BEFORE), [])[1], [])

    def test_the_input_resume_is_not_mutated(self):
        resume = copy.deepcopy(DANIEL_BEFORE)
        term_pipeline.strike_unsupported_claims(resume, UNSUPPORTED)
        self.assertEqual(resume, DANIEL_BEFORE)

    def test_a_flagged_claim_cannot_reach_the_saved_resume_even_when_the_edit_pass_fails(self):
        bad = copy.deepcopy(DANIEL_AFTER_EDIT)
        bad["experience"][0]["bullets"][3] = "Recorded 60 short lesson videos and applied video editing skills to support independent study."
        bad["summary"] = "Educator who works closely with subject matter experts. Piloted a new unit using pre/post-tests."
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, bad, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        everything = prose(result["resume_data"]) + " " + skills_text(result["resume_data"])
        for gone in ("video editing", "subject matter experts"):
            self.assertNotIn(gone, everything, gone)
        self.assertEqual(result["claim_review"], [])
        self.assertEqual(len(result["claims_struck"]), 2)
        self.assertIn("pre/post-tests", result["resume_data"]["summary"])  # the supported sentence stays

    def test_genuine_adjacent_experience_is_never_struck(self):
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, copy.deepcopy(DANIEL_AFTER_EDIT), DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertEqual(result["claims_struck"], [])
        self.assertIn("60 short lesson videos", prose(result["resume_data"]))
        self.assertIn("mentored two student teachers", prose(result["resume_data"]))

    def test_a_paraphrase_that_shares_the_denied_terms_words_is_caught(self):
        sneaky = copy.deepcopy(DANIEL_AFTER_EDIT)
        sneaky["experience"][0]["bullets"][3] = "Edited the lesson videos with editing software to polish each recording."
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, sneaky, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertNotIn("editing software", prose(result["resume_data"]))
        self.assertEqual(len(result["claims_struck"]), 1)

    def test_known_limit_a_paraphrase_that_shares_too_few_words_is_not_caught(self):
        sneaky = copy.deepcopy(DANIEL_AFTER_EDIT)
        sneaky["experience"][0]["bullets"][3] = "Polished each lesson recording before sharing it with students."
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, sneaky, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertIn("polished each lesson recording", prose(result["resume_data"]))  # a documented false negative (docs/TRUTHFULNESS.md)

    def test_sears_invented_banking_duties_are_struck_even_when_paraphrased_and_the_edit_pass_is_down(self):
        result, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, SEARS_BAD, fail_edit=True)
        text = prose(result["resume_data"])
        for gone in ("managed customer bank accounts", "regulated banking", "financial compliance", "reconciled the cash drawer", "banking professional"):
            self.assertNotIn(gone, text, gone)
        self.assertEqual(len(result["claims_struck"]), 3)
        self.assertEqual(result["claim_review"], [])
        self.assertIn("customer service", skills_text(result["resume_data"]))  # the genuine transferable skills stay

    def test_sears_genuine_wording_is_not_struck(self):
        result, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, copy.deepcopy(SEARS_GOOD), fail_edit=True)
        self.assertEqual(result["claims_struck"], [])
        self.assertIn("handled cash payments", prose(result["resume_data"]))
        self.assertIn("assisted customers", prose(result["resume_data"]))

    def test_a_sentence_made_of_the_candidates_own_words_is_not_struck_by_the_paraphrase_rule(self):
        profile = SEARS_PROFILE + "  * Balanced the cash drawer at the end of each shift.\n"
        plan = SEARS_PLAN
        resume = copy.deepcopy(SEARS_GOOD)
        resume["experience"][0]["bullets"][0] = "Balanced the cash drawer at the end of each shift."
        result, _ = run(profile, SEARS_POSTING, plan, resume, fail_edit=True)  # "cash drawer reconciliation" is still unsupported, but these are the candidate's words
        self.assertEqual(result["claims_struck"], [])
        self.assertIn("balanced the cash drawer", prose(result["resume_data"]))

    def test_an_invented_figure_is_flagged_by_the_quality_check_and_then_struck(self):
        invented = copy.deepcopy(DANIEL_AFTER_EDIT)
        invented["experience"][0]["bullets"][3] = "Recorded 60 short lesson videos that raised unit test scores by 35%."
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, invented, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertGreaterEqual(result["quality"]["found"], 1)  # flagged for the edit pass, never silent
        self.assertNotIn("35%", prose(result["resume_data"]))  # and, when the edit pass cannot fix it, struck by code (PR 33 review)


class SavedTruthReview(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
                        mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()

    def test_the_flags_are_saved_with_the_resume_and_returned_by_the_api(self):
        self.onboard(self.a)
        review = {"answer_conflicts": [{"fact": "f", "denied_question": "q", "shared": ["a", "b", "c"]}],
                  "skills_removed": ["Video Editing"], "claims_struck": [{"where": "summary", "text": "Works with subject matter experts."}],
                  "claim_review": [], "verb_review": [], "fact_verb_review": [], "verbs_restored": [], "lines_held": [],
                  "truth_notice": {"count": 2, "message": "We left out 2 statements we couldn’t verify. Review your experience to make sure nothing important is missing."}}

        def fake_build(profile_text, job_description, confirmed_facts, name, contact, denials, answers_text="", saved_terms=None):
            return {"resume_data": copy.deepcopy(SEARS_GOOD), "role_selection": [], "term_report": [], "ats_match": None, **review}

        with mock.patch("career.routes.build_checked_resume", fake_build):
            res = self.call("POST", "/job-build-resume", self.a, json={
                "job_description": "Bank Teller at Example Bank. Processes deposits and handles cash accurately.",
                "name": "Sam Ortiz", "contact": "Chicago, IL | s@example.com", "confirmed_facts": [], "qa_history": []})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["resume_data"]["truth_review"], review)
        saved = self.call("GET", "/resume-versions", self.a).json()
        self.assertEqual(saved[0]["resume_data"]["truth_review"], review)  # a reviewer can inspect it later

    def test_the_word_file_ignores_the_review(self):
        data = dict(copy.deepcopy(SEARS_GOOD), truth_review={"claims_struck": [{"where": "summary", "text": "SECRET-MARKER"}], "skills_removed": ["X"]})
        text = "\n".join(p.text for p in Document(io.BytesIO(rb.build_resume_bytes(data, ats_mode=False, template="classic"))).paragraphs)
        self.assertNotIn("SECRET-MARKER", text)
        self.assertIn("handled cash payments", text)


class StrikeInventedFigures(unittest.TestCase):
    """A figure (number, amount or percentage) the candidate never gave must not reach the saved or downloaded resume, even when the
    edit pass is unavailable. Names stay flagged-only (higher false-positive risk)."""

    def docx(self, resume):
        return "\n".join(p.text for p in Document(io.BytesIO(rb.build_resume_bytes(resume, ats_mode=False, template="classic"))).paragraphs)

    def invented(self, bullet):
        resume = copy.deepcopy(DANIEL_AFTER_EDIT)
        resume["experience"][0]["bullets"][3] = bullet
        return resume

    def test_a_sentence_with_an_invented_figure_is_struck_and_never_reaches_the_word_file(self):
        bad = self.invented("Recorded 60 short lesson videos that raised unit test scores by 35%.")
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, bad, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertNotIn("35%", prose(result["resume_data"]))
        self.assertNotIn("35%", self.docx(result["resume_data"]))
        self.assertEqual([s["reason"] for s in result["claims_struck"]], ["figure not in the candidate's evidence"])
        self.assertIn("35%", result["claims_struck"][0]["text"])  # the operator can see exactly what was removed

    def test_the_candidates_own_figures_are_kept_including_digits_for_spelled_out_numbers(self):
        for bullet in ("Recorded 60 short lesson videos during remote learning and shared them in Google Classroom.",
                       "Planned and taught 5 sections a day of grades 6 to 8 science.",   # evidence says "five sections ... 6 to 8"
                       "Built a year-long curriculum used by 4 other teachers.",           # evidence says "four other teachers"
                       "Mentored 2 student teachers."):                                    # evidence says "two student teachers"
            result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, self.invented(bullet), DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
            self.assertEqual([s for s in result["claims_struck"] if "figure" in s["reason"]], [], bullet)
            self.assertIn(bullet.split()[0], prose(result["resume_data"]).title() + prose(result["resume_data"]))

    def test_no_figure_is_struck_in_any_genuine_fixture(self):
        for built, profile, plan, history, facts in ((DANIEL_AFTER_EDIT, DANIEL_PROFILE, DANIEL_PLAN, DANIEL_HISTORY, [DANIEL_FACT]),
                                                     (DANIEL_BEFORE, DANIEL_PROFILE, DANIEL_PLAN, DANIEL_HISTORY, [DANIEL_FACT]),
                                                     (SEARS_GOOD, SEARS_PROFILE, SEARS_PLAN, [], [])):
            result, _ = run(profile, SEARS_POSTING if profile is SEARS_PROFILE else "posting", plan, copy.deepcopy(built), history, facts, fail_edit=True)
            self.assertEqual([s for s in result["claims_struck"] if "figure" in s["reason"]], [])

    def test_a_true_fact_in_the_same_sentence_as_an_invented_figure_goes_with_it(self):
        bad = self.invented("Recorded 60 short lesson videos that raised unit test scores by 35%.")
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, bad, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertFalse(any("60 short lesson videos" in b for b in result["resume_data"]["experience"][0]["bullets"]))  # documented cost
        split = self.invented("Recorded 60 short lesson videos. Raised unit test scores by 35%.")
        result2, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, split, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertEqual(result2["resume_data"]["experience"][0]["bullets"][3], "Recorded 60 short lesson videos.")  # separate sentences: the true one stays

    def test_an_invented_name_is_flagged_but_not_struck(self):
        bad = self.invented("Recorded 60 short lesson videos and tracked results in Tableau.")
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, bad, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertIn("Tableau", prose(result["resume_data"]).title())  # documented: names are flagged for the edit pass, not struck
        self.assertEqual(result["claims_struck"], [])

    def test_an_invented_figure_in_the_summary_or_headline_is_struck_too(self):
        resume = copy.deepcopy(DANIEL_AFTER_EDIT)
        resume["summary"] = "Educator with over 10 years of teaching experience. Raised school-wide scores by 50%."
        resume["headline"] = "Instructional Design | 200 Lessons Built"
        evidence = DANIEL_PROFILE + "2014 to 2025"
        out, struck = term_pipeline.strike_unsupported_claims(resume, [], evidence)
        self.assertEqual(out["summary"], "Educator with over 10 years of teaching experience.")
        self.assertEqual(out["headline"], "Instructional Design")
        self.assertEqual(sorted(s["where"] for s in struck), ["headline", "summary"])

    def test_without_evidence_the_figure_rule_does_nothing(self):
        resume = self.invented("Raised scores by 35%.")
        self.assertEqual(term_pipeline.strike_unsupported_claims(resume, [], ""), (resume, []))
        self.assertEqual(term_pipeline.invented_figures("Raised scores by 35%.", ""), [])

    def test_the_struck_figure_is_saved_in_the_truth_review(self):
        bad = self.invented("Recorded 60 short lesson videos that raised unit test scores by 35%.")
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, bad, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        review = {k: result[k] for k in ("answer_conflicts", "skills_removed", "claims_struck", "claim_review")}
        self.assertEqual(len(review["claims_struck"]), 1)
        self.assertEqual(review["claim_review"], [])


if __name__ == "__main__":
    unittest.main()
