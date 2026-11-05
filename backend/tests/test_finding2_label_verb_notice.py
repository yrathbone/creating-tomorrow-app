"""Finding 2, narrow safeguards (2026-11-03). Saved fictional data (Daniel Reyes), no model calls.

  1. An interview category label ("Video Production") is a heading for a question, never evidence of a qualification.
  2. The candidate's own verbs keep their strength: "recorded" is not "produced", "assisted" is not "managed".
  3. When statements are left out, the candidate sees one accurate line, and genuine transferable skills are not counted or removed.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import unittest

from career import resume_quality, term_pipeline
from career.term_pipeline import facts_text_for, truth_notice
from tests.test_finding2_live_fixes import LIVE_BUILT, LIVE_FACTS, LIVE_HISTORY, PLAN, POSTING
from tests.test_finding2_truthfulness import DANIEL_PROFILE, prose, run, skills_text

LABEL_FACTS = [{"id": "f4", "category": "Video Production", "bullet_text": "Recorded 60 short lesson videos for remote learning, shared in Google Classroom."}]
VIDEO_PLAN = PLAN + [{"term": "Video Production", "importance": "preferred", "kind": "skill", "support": "none", "evidence": ""}]


class A_CategoryLabelsAreNotEvidence(unittest.TestCase):
    def test_the_text_the_planner_and_the_checks_read_holds_only_what_the_candidate_confirmed(self):
        text = facts_text_for(LABEL_FACTS)
        self.assertNotIn("Video Production", text)
        self.assertIn("Recorded 60 short lesson videos", text)
        self.assertEqual(facts_text_for([]), "(none confirmed)")

    def test_a_label_alone_does_not_make_a_claim_supported(self):
        evidence = DANIEL_PROFILE + "\n" + facts_text_for(LABEL_FACTS)
        built = copy.deepcopy(LIVE_BUILT)
        built["summary"] = "Teacher with eleven years in science. Led video production for a remote-learning program."
        result, seen = run(DANIEL_PROFILE, POSTING, VIDEO_PLAN, built, LIVE_HISTORY, LABEL_FACTS, fail_edit=True)
        self.assertNotIn("video production", prose(result["resume_data"]))
        self.assertTrue(any("video production" in s["text"].lower() for s in result["claims_struck"]), result["claims_struck"])
        self.assertNotIn("(Video Production)", seen["career_job_build_resume"]["user"])  # the writer is not shown the label either
        self.assertNotIn("(Video Production)", evidence)

    def test_the_true_fact_behind_the_label_is_still_usable(self):
        built = copy.deepcopy(LIVE_BUILT)
        built["experience"][0]["bullets"].append("Recorded 60 short lesson videos for remote learning, shared in Google Classroom.")
        result, _ = run(DANIEL_PROFILE, POSTING, VIDEO_PLAN, built, LIVE_HISTORY, LABEL_FACTS, fail_edit=True)
        self.assertIn("recorded 60 short lesson videos", prose(result["resume_data"]))


class B_VerbsKeepTheirStrength(unittest.TestCase):
    EVIDENCE = "Recorded 60 short lesson videos. Assisted the department head with scheduling. Helped plan units."

    def resume(self, summary="", bullets=()):
        return {"summary": summary, "experience": [{"title": "Teacher", "bullets": list(bullets)}]}

    def test_produced_for_recorded_is_flagged(self):
        flags = resume_quality.verb_upgrades(self.resume(bullets=["Produced 60 short lesson videos for remote learning."]), self.EVIDENCE)
        self.assertEqual([(f["written"], f["evidence_verb"]) for f in flags], [("produced", "recorded")])

    def test_managed_and_led_for_assisted_or_helped_are_flagged(self):
        flags = resume_quality.verb_upgrades(self.resume(bullets=["Managed scheduling for the department.", "Led unit planning."]), self.EVIDENCE)
        self.assertEqual({f["written"] for f in flags}, {"managed", "led"})

    def test_the_candidates_own_verb_is_not_flagged(self):
        resume = self.resume(bullets=["Recorded 60 short lesson videos.", "Assisted the department head with scheduling.", "Helped plan units."])
        self.assertEqual(resume_quality.verb_upgrades(resume, self.EVIDENCE), [])

    def test_a_strong_verb_the_candidate_used_is_fine(self):
        evidence = self.EVIDENCE + " I led the science fair committee and managed its budget."
        self.assertEqual(resume_quality.verb_upgrades(self.resume(bullets=["Led the science fair committee.", "Managed its budget."]), evidence), [])
        self.assertEqual(resume_quality.verb_upgrades(self.resume(bullets=["Produced a field guide."]), "Wrote a field guide."), [])  # no weaker verb to compare with

    def test_led_is_not_matched_inside_other_words(self):
        self.assertEqual(resume_quality.verb_upgrades(self.resume(bullets=["Led unit planning."]), "Kept the ledger and the leadership log."), [])

    def test_the_pipeline_restores_it_when_the_candidates_own_sentence_covers_it(self):
        built = copy.deepcopy(LIVE_BUILT)
        built["experience"][0]["bullets"].append("Produced 60 short lesson videos for remote learning.")
        facts = [{"id": "f", "category": "Video", "bullet_text": "Recorded 60 short lesson videos for remote learning."}]
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, built, LIVE_HISTORY, facts, fail_edit=True)
        self.assertIn("recorded 60 short lesson videos for remote learning", prose(result["resume_data"]))
        self.assertNotIn("produced 60 short lesson videos", prose(result["resume_data"]))
        self.assertEqual(len(result["verbs_restored"]), 1)
        self.assertEqual(result["lines_held"], [])
        self.assertEqual(result["verb_review"], [])

    def test_the_writer_prompts_say_so(self):
        from career import job_match
        self.assertIn('"recorded" stays "recorded"', job_match.TAILORED_SYSTEM_PROMPT if hasattr(job_match, "TAILORED_SYSTEM_PROMPT") else open(job_match.__file__, encoding="utf8").read())
        import elevate
        self.assertIn('Do not upgrade "recorded" to "produced"', open(elevate.__file__, encoding="utf8").read())


class C_TheCandidateNotice(unittest.TestCase):
    def test_wording_and_counts(self):
        self.assertEqual(truth_notice([], []), {"count": 0, "message": "", "held": [], "held_message": "", "restored_message": ""})
        self.assertEqual(truth_notice([{}], [])["message"], "We left out 1 statement we couldn’t verify. Review your experience to make sure nothing important is missing.")
        self.assertEqual(truth_notice([{}, {}], ["a"])["count"], 3)
        self.assertTrue(truth_notice([{}, {}], ["a"])["message"].startswith("We left out 3 statements we couldn’t verify."))

    def test_the_count_through_the_pipeline_is_exactly_what_was_left_out(self):
        built = copy.deepcopy(LIVE_BUILT)
        built["summary"] = "Teacher with eleven years in science. Skilled in Articulate Storyline modules."
        built["skills"] = built["skills"] + ["E-learning: Articulate Storyline"]
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, built, LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        expected = len(result["claims_struck"]) + len(result["skills_removed"])
        self.assertGreaterEqual(expected, 1)
        self.assertEqual(result["truth_notice"]["count"], expected)
        self.assertIn(f"We left out {expected} ", result["truth_notice"]["message"])
        self.assertNotIn("articulate storyline", (prose(result["resume_data"]) + skills_text(result["resume_data"])))

    def test_nothing_left_out_means_no_notice(self):
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, copy.deepcopy(LIVE_BUILT), LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        if not (result["claims_struck"] or result["skills_removed"]):
            self.assertEqual(result["truth_notice"], {"count": 0, "message": ""})
        else:  # the saved live writer output loses only what the checks removed, and the count says so
            self.assertEqual(result["truth_notice"]["count"], len(result["claims_struck"]) + len(result["skills_removed"]))

    def test_one_claim_is_counted_once(self):
        sentence = {"where": "summary", "text": "Skilled in video editing for lesson videos.", "reason": "unsupported claim"}
        # a removed skill that a struck sentence also names counts with that sentence
        self.assertEqual(truth_notice([sentence], ["Video Editing"])["count"], 1)
        # the same sentence struck in two places is one statement
        self.assertEqual(truth_notice([sentence, dict(sentence, where="bullet")], [])["count"], 1)
        # a skill named nowhere else, and a repeated skill, count once each
        self.assertEqual(truth_notice([sentence], ["Articulate Storyline", "Articulate Storyline"])["count"], 2)

    def test_through_the_pipeline_a_claim_in_both_places_is_one_statement(self):
        built = copy.deepcopy(LIVE_BUILT)
        built["summary"] = "Teacher with eleven years in science. Skilled in video editing for lesson videos."
        built["skills"] = ["Media: Screencastify, Video Editing", "Teaching: Teaching, Curriculum Design"]
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, built, LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        self.assertTrue(any("video editing" in s["text"].lower() for s in result["claims_struck"]))
        self.assertIn("Video Editing", result["skills_removed"])
        self.assertEqual(result["truth_notice"]["count"], 1)

    def test_verified_accomplishments_stay_intact(self):
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, copy.deepcopy(LIVE_BUILT), LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        text = prose(result["resume_data"])
        for kept in ("designed a year-long project-based curriculum", "adopted and used by four other teachers", "mentored two student teachers",
                     "collaborated with fellow science teachers"):
            self.assertIn(kept, text)

    def test_the_interview_step_upgrading_a_verb_is_reported_for_a_confirmed_fact(self):
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, copy.deepcopy(LIVE_BUILT), LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        flagged = [f["written"] + ">" + f["evidence_verb"] for f in result["fact_verb_review"]]
        self.assertEqual(flagged, ["produced>recorded"], flagged)  # the live "Produced 60 short instructional videos" fact; the other four facts are fine

    def test_genuine_transferable_skills_stay_and_are_not_counted(self):
        plan = PLAN + [{"term": "Mentoring", "importance": "preferred", "kind": "skill", "support": "transferable", "evidence": "Mentored two student teachers."}]
        built = copy.deepcopy(LIVE_BUILT)
        built["skills"] = list(built["skills"]) + ["Training: Mentoring"]
        result, _ = run(DANIEL_PROFILE, POSTING, plan, built, LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        self.assertIn("mentoring", skills_text(result["resume_data"]))
        self.assertNotIn("Mentoring", result["skills_removed"])
        self.assertTrue(all("mentor" not in s["text"].lower() for s in result["claims_struck"]))


if __name__ == "__main__":
    unittest.main()
