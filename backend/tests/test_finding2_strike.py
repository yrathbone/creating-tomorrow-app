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
    DANIEL_AFTER_EDIT, DANIEL_BEFORE, DANIEL_FACT, DANIEL_HISTORY, DANIEL_PLAN, DANIEL_PROFILE, SEARS_GOOD, prose, run, skills_text,
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
        self.assertEqual(len(bullets), 4)  # the e-learning bullet is gone entirely (both its sentences were unsupported), not rewritten
        self.assertNotIn("e-learning modules", " ".join(bullets).lower())
        self.assertNotIn("video editing", " ".join(bullets).lower())
        self.assertEqual(len(struck), 5)  # three summary sentences and the two sentences of that bullet
        # known limit: "subject matter resource" is not the planned term "subject matter experts", so that bullet is not struck
        self.assertIn("subject matter resource", " ".join(bullets).lower())

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

    def test_known_limit_a_paraphrase_that_uses_no_planned_term_is_not_caught(self):
        sneaky = copy.deepcopy(DANIEL_AFTER_EDIT)
        sneaky["experience"][0]["bullets"][3] = "Edited the lesson recordings with editing software to polish each video."
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, sneaky, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertIn("editing software", prose(result["resume_data"]))  # a documented false negative (docs/TRUTHFULNESS.md)

    def test_an_invented_figure_is_flagged_by_the_existing_quality_check_but_not_struck(self):
        invented = copy.deepcopy(DANIEL_AFTER_EDIT)
        invented["experience"][0]["bullets"][3] = "Recorded 60 short lesson videos that raised unit test scores by 35%."
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, invented, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        self.assertGreaterEqual(result["quality"]["found"], 1)  # flagged for the edit pass, never silent
        self.assertIn("35%", prose(result["resume_data"]))  # documented: figures are flagged, not struck


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
                  "claim_review": []}

        def fake_build(profile_text, job_description, confirmed_facts, name, contact, denials):
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


if __name__ == "__main__":
    unittest.main()
