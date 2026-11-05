"""Finding 2: a verb stronger than the candidate's own is RESTORED to their meaning when their words unambiguously cover it, or HELD
out of the resume (and the Word file) for clarification. Saved fictional data, no model calls.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import io
import unittest

from docx import Document

import resume_builder as rb
from career import resume_quality
from career.resume_quality import candidate_answers_text, resolve_verb_upgrades
from career.term_pipeline import truth_notice
from tests.test_finding2_live_fixes import LIVE_BUILT, LIVE_HISTORY, PLAN, POSTING
from tests.test_finding2_truthfulness import DANIEL_PROFILE, prose, run, skills_text


def resume(*bullets, summary=""):
    return {"summary": summary, "experience": [{"title": "Teacher", "bullets": list(bullets)}]}


def bullets_of(r):
    return [b for j in r["experience"] for b in j["bullets"]]


class A_RestoredWhenTheCandidatesOwnWordsCoverIt(unittest.TestCase):
    def test_recorded_versus_produced_only_the_verb_changes_and_the_rest_of_the_line_stays(self):
        out, restored, held = resolve_verb_upgrades(
            resume("Produced 60 short instructional videos using Screencastify for remote learning."),
            "Recorded 60 short lesson videos for remote learning.")
        self.assertEqual(bullets_of(out), ["Recorded 60 short instructional videos using Screencastify for remote learning."])
        self.assertEqual(held, [])
        self.assertEqual((restored[0]["before"][:8], restored[0]["after"][:8]), ("Produced", "Recorded"))

    def test_helped_versus_led_uses_the_candidates_own_short_sentence(self):
        out, restored, held = resolve_verb_upgrades(resume("Led unit planning."), "Helped plan units.")
        self.assertEqual(bullets_of(out), ["Helped plan units."])
        self.assertEqual(held, [])
        self.assertIn("own sentence", restored[0]["basis"])

    def test_a_line_with_a_figure_the_evidence_lacks_is_held_not_rewritten(self):
        out, restored, held = resolve_verb_upgrades(resume("Led unit planning that cut prep time by 20%."), "Helped plan units.")
        self.assertEqual(bullets_of(out), [])
        self.assertEqual(restored, [])
        self.assertEqual(held[0]["text"], "Led unit planning that cut prep time by 20%.")  # kept word for word for the candidate


class B_StrongerWordingTheEvidenceSupportsIsKept(unittest.TestCase):
    def test_a_verb_the_candidate_used_is_untouched(self):
        evidence = "I led the science fair committee for three years. Helped plan units."
        out, restored, held = resolve_verb_upgrades(resume("Led the science fair committee for three years.", "Helped plan units."), evidence)
        self.assertEqual(bullets_of(out), ["Led the science fair committee for three years.", "Helped plan units."])
        self.assertEqual((restored, held), ([], []))

    def test_the_candidates_typed_interview_answer_supports_the_stronger_verb(self):
        history = [{"type": "detail", "question": "Tell us more.", "answer": "I produced the whole 60-video series myself."},
                   {"type": "yes_no", "question": "Did you edit them?", "answer": "no"}, {"type": "detail", "question": "More?", "answer": "skip"}]
        typed = candidate_answers_text(history)
        self.assertEqual(typed, "I produced the whole 60-video series myself.")  # the tool's questions, yes/no and skips are not wording
        out, restored, held = resolve_verb_upgrades(resume("Produced 60 short lesson videos."), "Recorded 60 short lesson videos.\n" + typed)
        self.assertEqual((bullets_of(out), restored, held), (["Produced 60 short lesson videos."], [], []))


class C_AmbiguousEvidenceIsHeldNotGuessed(unittest.TestCase):
    def test_two_different_candidate_sentences_that_both_fit_means_hold(self):
        evidence = "Helped plan units.\nAssisted with unit planning meetings."
        out, restored, held = resolve_verb_upgrades(resume("Led unit planning."), evidence)
        self.assertEqual((bullets_of(out), restored), ([], []))
        self.assertEqual(len(held), 1)

    def test_no_candidate_sentence_describes_the_activity_means_hold(self):
        out, restored, held = resolve_verb_upgrades(resume("Oversaw the school budget."), "Helped plan units. Assisted at the library desk.")
        self.assertEqual((bullets_of(out), restored), ([], []))
        self.assertEqual(len(held), 1)

    def test_the_verb_check_never_fires_without_a_weaker_verb_to_compare_with(self):
        out, restored, held = resolve_verb_upgrades(resume("Oversaw the school budget."), "Wrote the school budget report.")
        self.assertEqual((bullets_of(out), restored, held), (["Oversaw the school budget."], [], []))

    def test_a_held_line_does_not_take_the_other_sentences_of_the_bullet_with_it(self):
        out, restored, held = resolve_verb_upgrades(resume("Taught five sections a day. Led unit planning that cut prep time by 20%."), "Taught five sections a day. Helped plan units.")
        self.assertEqual(bullets_of(out), ["Taught five sections a day."])
        self.assertEqual(len(held), 1)


class D_ThroughThePipeline(unittest.TestCase):
    FACTS = [{"id": "f4", "category": "Video", "bullet_text": "Produced 60 short instructional videos using Screencastify for remote learning."},
             {"id": "f1", "category": "Teaching", "bullet_text": "Designed a year-long project-based science curriculum that was adopted and used by four other teachers."}]

    def built(self, *extra):
        built = copy.deepcopy(LIVE_BUILT)
        built["experience"][0]["bullets"] = list(built["experience"][0]["bullets"]) + list(extra)
        return built

    def test_an_interview_upgraded_fact_is_restored_in_the_resume_and_the_other_accomplishments_stay(self):
        built = self.built("Produced 60 short instructional videos using Screencastify for remote learning.")
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, built, LIVE_HISTORY, self.FACTS, fail_edit=True)
        text = prose(result["resume_data"])
        self.assertIn("recorded 60 short instructional videos using screencastify", text)
        self.assertNotIn("produced 60", text)
        for kept in ("designed a year-long project-based curriculum", "adopted and used by four other teachers", "mentored two student teachers"):
            self.assertIn(kept, text)
        self.assertEqual(len(result["verbs_restored"]), 1)
        self.assertEqual(result["lines_held"], [])
        self.assertEqual(result["verb_review"], [])
        self.assertEqual([f["written"] for f in result["fact_verb_review"]], ["produced"])  # the upgraded FACT is still reported

    def test_a_held_line_is_out_of_the_resume_and_the_word_file_and_is_told_to_the_candidate(self):
        built = self.built("Oversaw the science department budget.")
        profile = DANIEL_PROFILE + "\n  * Assisted the department chair with ordering supplies."
        result, _ = run(profile, POSTING, PLAN, built, LIVE_HISTORY, self.FACTS, fail_edit=True)
        self.assertEqual([h["text"] for h in result["lines_held"]], ["Oversaw the science department budget."])
        self.assertNotIn("department budget", prose(result["resume_data"]))
        word = "\n".join(p.text for p in Document(io.BytesIO(rb.build_resume_bytes(result["resume_data"], ats_mode=False, template="classic"))).paragraphs)
        self.assertNotIn("department budget", word)
        self.assertIn("year-long project-based curriculum", word)  # the verified accomplishments are in the file
        notice = result["truth_notice"]
        self.assertEqual(notice["held"][0]["text"], "Oversaw the science department budget.")
        self.assertIn("We held 1 line out of your résumé until you confirm it.", notice["held_message"])
        self.assertIn("not in your Word file yet", notice["held_message"])
        self.assertIn("tell us more about what you did in the interview, then rebuild your résumé", notice["held_message"])

    def test_held_lines_are_counted_apart_from_left_out_statements_and_once_each(self):
        sentence = {"where": "summary", "text": "Skilled in video editing.", "reason": "unsupported claim"}
        held = [{"text": "Led the budget.", "evidence_verb": "helped"}, {"text": "Led the budget.", "evidence_verb": "helped"}]
        notice = truth_notice([sentence], ["Video Editing"], held)
        self.assertEqual(notice["count"], 1)  # the left-out count is unchanged by held lines
        self.assertEqual(len(notice["held"]), 1)  # the same line held in two places is one line
        self.assertIn("We held 1 line", notice["held_message"])
        self.assertEqual(truth_notice([], [], [{"text": "a", "evidence_verb": ""}, {"text": "b", "evidence_verb": ""}])["held_message"][:16], "We held 2 lines ")
        self.assertEqual(truth_notice([], [], [])["held_message"], "")
        self.assertTrue(truth_notice([], [], [], [{}])["restored_message"].startswith("We put 1 line back to the wording you gave us"))
        self.assertEqual(truth_notice([], [], [], [])["restored_message"], "")

    def test_transferable_skills_and_the_left_out_count_are_unaffected(self):
        plan = PLAN + [{"term": "Mentoring", "importance": "preferred", "kind": "skill", "support": "transferable", "evidence": "Mentored two student teachers."}]
        built = self.built("Oversaw the science department budget.")
        built["skills"] = list(built["skills"]) + ["Training: Mentoring"]
        profile = DANIEL_PROFILE + "\n  * Assisted the department chair with ordering supplies."
        result, _ = run(profile, POSTING, plan, built, LIVE_HISTORY, self.FACTS, fail_edit=True)
        self.assertIn("mentoring", skills_text(result["resume_data"]))
        self.assertNotIn("Mentoring", result["skills_removed"])
        self.assertEqual(len(result["lines_held"]), 1)
        self.assertEqual(result["truth_notice"]["count"], len(result["claims_struck"]) + len(result["skills_removed"]))

    def test_the_truth_review_keeps_restored_and_held_apart(self):
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, self.built("Produced 60 short instructional videos using Screencastify for remote learning."),
                        LIVE_HISTORY, self.FACTS, fail_edit=True)
        self.assertTrue(result["verbs_restored"] and not result["lines_held"])
        for entry in result["verbs_restored"]:
            self.assertEqual(set(entry), {"where", "before", "after", "basis"})


if __name__ == "__main__":
    unittest.main()
