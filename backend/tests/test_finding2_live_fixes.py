"""Fixes found by the LIVE Daniel Reyes rerun (2026-11-03, saved resume version 31). Fictional data only.

The live rerun showed three problems in our own checks, not in the candidate's resume:
  A. a true fact about assessments tracked in Google Sheets was reported as conflicting with a No about "other software to build
     digital learning content" (three incidental shared words: "based", "google", "learn");
  B. "K-12" was read as the invented figure "12", so a true headline phrase and summary sentence were struck;
  C. the struck sentence also said "Instructional Designer with ..." (the posting's job title, which Daniel never held), a
     misstatement that only the false K-12 strike had been catching, so enforcing "never state the target" is now explicit.
The facts, answers and writer output below are the ones the live run produced.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import unittest

from career import resume_quality, term_pipeline
from career.resume_quality import denials_from_history, distinct_roots, find_conflicts
from career.term_pipeline import invented_figures, plan_terms, posting_title
from tests.test_finding2_truthfulness import DANIEL_PLAN, DANIEL_PROFILE, fake_ai, prose, run, skills_text

POSTING = ("Instructional Designer\nBrightpath Learning Solutions\n\nWe design onboarding and compliance training for mid-size employers. "
           "Requirements: 3+ years of instructional design or teaching; strong writing; experience with an LMS; ability to work with subject matter experts.")

Q_OTHER_SOFTWARE = ("Even if not Articulate Storyline or Rise, have you used any other software to build digital or online learning content - like "
                    "PowerPoint-based modules, Google Slides, Canva, an LMS's built-in course builder, or something else?")
LIVE_HISTORY = [
    {"id": "q1", "type": "yes_no", "answer": "no", "category": "E-learning authoring tools: Articulate Storyline/Rise (required)",
     "question": "Have you ever used Articulate Storyline, Rise, or a similar e-learning authoring tool to build a training module?"},
    {"id": "q2", "type": "yes_no", "answer": "no", "category": "Working with subject matter experts to build training content (required)",
     "question": "Have you worked directly with specialists or experts outside your own field (such as administrators, counselors, or industry professionals) to develop instructional materials?"},
    {"id": "q3", "type": "yes_no", "answer": "no", "category": "Corporate training experience (preferred)",
     "question": "Have you designed or delivered any training for adults in a workplace or corporate setting, rather than K-12 students?"},
    {"id": "q4", "type": "yes_no", "answer": "no", "category": "ADDIE or SAM instructional design models (preferred)",
     "question": "Are you familiar with or have you applied a formal instructional design model like ADDIE or SAM in planning your curriculum?"},
    {"id": "q5", "type": "yes_no", "answer": "no", "category": "Video editing (preferred)",
     "question": "Did you edit the 60 lesson videos you recorded (e.g., cutting, adding captions, or assembling clips) rather than just recording them straight through?"},
    {"id": "q6", "type": "yes_no", "answer": "no", "category": "E-learning authoring tools", "question": Q_OTHER_SOFTWARE},
    {"id": "q7", "type": "yes_no", "answer": "yes", "category": "Working with others on content",
     "question": "Have you ever worked with colleagues (like other teachers, staff, or outside presenters) to put together lesson plans, workshops, or training materials together?"},
    {"id": "q8", "type": "yes_no", "answer": "yes", "category": "Training/assessment",
     "question": "Have you ever measured whether your teaching or training was effective - for example, through quizzes, surveys, feedback forms, or test scores - and used that to make changes?"},
]
LIVE_DENIALS = denials_from_history(LIVE_HISTORY)
LIVE_FACTS = [
    {"id": "f1", "category": "Teaching/Curriculum Design", "bullet_text": "Taught middle school science (grades 6-8), five sections a day, for eleven years at Fox Valley Middle School."},
    {"id": "f2", "category": "Teaching/Curriculum Design", "bullet_text": "Designed a year-long project-based science curriculum that was adopted and used by four other teachers."},
    {"id": "f3", "category": "Working with subject matter experts to build training content", "bullet_text": "Collaborated with fellow science teachers at Fox Valley Middle School, sharing lesson plans and meeting regularly to plan units together."},
    {"id": "f4", "category": "Video recording/production", "bullet_text": "Produced 60 short instructional videos using Screencastify for remote learning, distributed via Google Classroom."},
    {"id": "f5", "category": "Training/Assessment", "bullet_text": "Developed and administered pre- and post-unit assessments to measure student learning, tracked results in Google Sheets, and adjusted subsequent lessons based on performance data."},
]
# the writer's output in the live run, before the checks ran
LIVE_BUILT = {
    "name": "Daniel Reyes", "contact": "Aurora, IL | (630) 555-0112 | daniel.reyes@example.com",
    "headline": "Curriculum Design | Instructional Content Development | K-12 Education",
    "summary": ("Instructional Designer with K-12 education experience building curriculum, assessments, and instructional content for diverse learners. "
                "Skilled at collaborating with colleagues to plan and deliver units. Experienced in classroom management, with hands-on LMS experience in Google Classroom and Canvas LMS."),
    "skills": ["Teaching & Learning Systems: Teaching, K-12 Education, LMS, Google Classroom, Canvas LMS, Classroom Management",
               "Media & Tools: Screencastify", "Professional Skills: Collaboration, Mentoring, Communication Skills"],
    "experience": [{"title": "Science Teacher", "subtitle": "Fox Valley Middle School, IL — 2014 – 2025", "bullets": [
        "Planned and taught five sections a day of grades 6-8 science.",
        "Designed a year-long project-based curriculum that was adopted and used by four other teachers.",
        "Collaborated with fellow science teachers, sharing lesson plans and meeting regularly to plan units together.",
        "Mentored two student teachers."]}],
    "education": ["Western Illinois University: M.Ed., Curriculum and Instruction (2016)"], "certifications": [],
}
PLAN = DANIEL_PLAN + [{"term": "Instructional Designer", "importance": "required", "kind": "skill", "support": "related", "evidence": "Curriculum design"}]


class A_ConflictsAreAboutTheDeniedSubject(unittest.TestCase):
    def test_no_live_fact_conflicts_with_any_live_denial(self):
        self.assertEqual(find_conflicts(LIVE_DENIALS, LIVE_FACTS), [])

    def test_the_old_whole_question_rule_would_have_flagged_the_assessment_fact(self):
        # documents the cause: three incidental words in common with the whole question
        shared = distinct_roots(LIVE_FACTS[4]["bullet_text"]) & distinct_roots(resume_quality._scope_text(Q_OTHER_SOFTWARE))
        self.assertGreaterEqual(len(shared), 3, shared)

    def test_a_fact_that_really_repeats_a_denial_is_still_a_conflict(self):
        for text, expected in (("Edited the lesson videos with video editing software.", "video"),
                               ("Built a module in Articulate Storyline.", "articulat"),
                               ("Applied the ADDIE model to plan my units.", "addi")):
            conflicts = find_conflicts(LIVE_DENIALS + [{"question": "Have you used ADDIE?", "category": "ADDIE"}], [{"bullet_text": text}])
            self.assertEqual(len(conflicts), 1, text)
            self.assertIn(expected, " ".join(conflicts[0]["shared"]), text)

    def test_a_subject_with_one_distinctive_word_needs_only_that_word(self):
        denial = [{"question": "Have you used ADDIE?", "category": "ADDIE"}]
        self.assertEqual(len(find_conflicts(denial, [{"bullet_text": "Used ADDIE on my units."}])), 1)
        self.assertEqual(find_conflicts(denial, [{"bullet_text": "Planned my units carefully."}]), [])

    def test_without_a_gap_name_the_question_stands_in_and_three_shared_words_are_needed(self):
        denial = [{"question": "Have you ever managed a regional sales budget for a retail chain?", "category": ""}]
        self.assertEqual(find_conflicts(denial, [{"bullet_text": "Managed a regional sales budget for a retail chain."}])[0]["shared"][:1] != [], True)
        self.assertEqual(find_conflicts(denial, [{"bullet_text": "Managed a sales team."}]), [])  # two shared words are not enough

    def test_through_the_pipeline_the_assessment_fact_is_not_held_back_and_reaches_the_writer(self):
        result, seen = run(DANIEL_PROFILE, POSTING, PLAN, copy.deepcopy(LIVE_BUILT), LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        self.assertEqual(result["answer_conflicts"], [])
        self.assertIn("Developed and administered pre- and post-unit assessments", seen["career_job_build_resume"]["user"])


class B_SchoolRangeIsNotAFigure(unittest.TestCase):
    EVIDENCE = DANIEL_PROFILE + "\n" + term_pipeline.facts_text_for(LIVE_FACTS)

    def test_k12_in_any_common_form_is_not_an_invented_figure(self):
        for text in ("Instructional Designer with K-12 education experience building curriculum.", "Experience in K12 classrooms.",
                     "Taught pre-K-12 science.", "Worked across K–12 schools.", "Skills: K-12 Education"):
            self.assertEqual(invented_figures(text, self.EVIDENCE), [], text)
            self.assertEqual(resume_quality._numbers(text), [], text)

    def test_a_real_invented_figure_next_to_k12_is_still_caught(self):
        flagged = invented_figures("Taught K-12 students and raised scores by 35%.", self.EVIDENCE)
        self.assertEqual(len(flagged), 1)
        self.assertIn('"35"', flagged[0])
        self.assertEqual(len(invented_figures("Taught 12 students in K-12 classrooms.", self.EVIDENCE)), 1)  # a bare 12 is still a number

    def test_through_the_pipeline_k12_text_is_kept_everywhere(self):
        built = copy.deepcopy(LIVE_BUILT)
        built["summary"] = "Teacher with K-12 education experience building curriculum and assessments. Skilled at collaborating with colleagues."
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, built, LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        self.assertEqual([s for s in result["claims_struck"] if "figure" in s["reason"]], [])
        self.assertIn("K-12 Education", result["resume_data"]["headline"])
        self.assertIn("K-12 education experience", result["resume_data"]["summary"])
        self.assertIn("K-12 Education", " ".join(result["resume_data"]["skills"]))


class C_NeverStateTheTarget(unittest.TestCase):
    def test_the_posting_title_is_its_short_first_line(self):
        self.assertEqual(posting_title(POSTING), "Instructional Designer")
        self.assertEqual(posting_title("Job title: Senior Customer Success Manager\nAcme"), "Senior Customer Success Manager")
        self.assertEqual(posting_title("\n\n  Bank Teller  \nExample Bank"), "Bank Teller")
        self.assertEqual(posting_title("We are hiring a creative designer to join our growing team today."), "")  # a sentence, not a title
        self.assertEqual(posting_title(""), "")

    def test_a_planner_term_equal_to_the_title_is_never_supported_unless_the_evidence_says_it(self):
        with __import__("unittest").mock.patch.object(term_pipeline.job_match, "_call_with_retry", fake_ai(plan=PLAN)):
            terms = {t["term"]: t for t in plan_terms(DANIEL_PROFILE, "(none)", POSTING, LIVE_DENIALS)}
        self.assertEqual(terms["Instructional Designer"]["support"], "none")
        self.assertNotEqual(terms["instructional design"]["support"], "none")  # the skill (not the title) is untouched

    def test_a_sentence_calling_the_candidate_the_posting_title_is_struck_and_the_rest_of_the_summary_stays(self):
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, copy.deepcopy(LIVE_BUILT), LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        summary = result["resume_data"]["summary"]
        self.assertNotIn("Instructional Designer", summary)
        self.assertIn("collaborating with colleagues", summary)
        reasons = {s["text"][:30]: s["reason"] for s in result["claims_struck"]}
        self.assertEqual(reasons.get("Instructional Designer with K-"), "unsupported claim")
        self.assertEqual(result["claim_review"], [])

    def test_instructional_design_as_a_skill_is_not_the_title_and_is_not_struck(self):
        built = copy.deepcopy(LIVE_BUILT)
        built["summary"] = "Teacher with strong instructional design skills and hands-on LMS experience."
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, built, LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        self.assertIn("instructional design skills", result["resume_data"]["summary"])
        self.assertEqual(result["claims_struck"], [])

    def test_a_candidate_who_really_held_the_title_is_not_struck(self):
        profile = DANIEL_PROFILE + "- Instructional Designer at Acme Learning (2012 – 2014)\n"
        built = copy.deepcopy(LIVE_BUILT)
        built["summary"] = "Instructional Designer with classroom teaching experience."
        result, _ = run(profile, POSTING, PLAN, built, [], [], fail_edit=True)
        self.assertEqual(result["claims_struck"], [])
        self.assertIn("Instructional Designer", result["resume_data"]["summary"])

    def test_the_live_resume_version_31_text_is_unchanged_by_the_new_checks(self):
        v31 = copy.deepcopy(LIVE_BUILT)
        v31["summary"] = ("Proven ability to design project-based learning adopted across a teaching team and produce instructional video content for remote learning. "
                          "Skilled at collaborating with colleagues to plan and deliver units.")
        v31["headline"] = "Curriculum Design | Instructional Content Development"
        result, _ = run(DANIEL_PROFILE, POSTING, PLAN, v31, LIVE_HISTORY, LIVE_FACTS, fail_edit=True)
        self.assertEqual(result["claims_struck"], [])  # nothing genuine is removed
        for kept in ("collaborating with colleagues", "instructional content development"):
            self.assertIn(kept, prose(result["resume_data"]))
        self.assertIn("screencastify", skills_text(result["resume_data"]))


if __name__ == "__main__":
    unittest.main()


class D_LongGapLabelsDoNotDenyGeneralSkills(unittest.TestCase):
    """The live ADDIE gap was labelled "ADDIE or SAM instructional design models (preferred)"; a term sitting inside that label is
    denied only when it makes up at least half of the label's distinctive words."""

    def test_instructional_design_is_not_denied_by_a_no_to_addie_or_sam(self):
        self.assertIsNone(resume_quality.denied_by("instructional design", LIVE_DENIALS))

    def test_the_things_actually_denied_still_are(self):
        for term in ("video editing", "corporate training", "subject matter experts", "Articulate Storyline"[:0] or "video editing"):
            self.assertIsNotNone(resume_quality.denied_by(term, LIVE_DENIALS), term)

    def test_through_the_planner_the_general_skill_stays_supported_and_the_denied_ones_do_not(self):
        with __import__("unittest").mock.patch.object(term_pipeline.job_match, "_call_with_retry", fake_ai(plan=PLAN)):
            terms = {t["term"]: t for t in plan_terms(DANIEL_PROFILE, "(none)", POSTING, LIVE_DENIALS)}
        self.assertEqual(terms["instructional design"]["support"], "related")
        for denied in ("video editing", "corporate training", "subject matter experts"):
            self.assertEqual(terms[denied]["support"], "none", denied)
