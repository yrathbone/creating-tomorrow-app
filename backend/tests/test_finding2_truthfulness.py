"""Finding 2 (Checkpoint B): truthful, transferable and keyword-aware targeted resumes. Fictional data only.

Governing principle: discover the value, preserve the truth, communicate the potential. Each test checks both that fabricated
content is gone AND that the candidate's genuine (confirmed and transferable) value is kept. The AI calls are replaced by fixed
answers, so these tests check the CODE around the model (what it is told, what is forced, what is removed, what is reported);
they cannot prove what a live model will write. See docs/TRUTHFULNESS.md for the limits.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import os
import unittest
from unittest import mock

import abuse_guard
from career import job_match, resume_quality, term_pipeline
from career.job_match import JobMatchError
from career.resume_quality import denials_from_history, denied_by, find_claim_issues, find_conflicts
from career.term_pipeline import build_checked_resume, plan_terms, sanitize_skills
from tests.test_ownership import OwnershipTestCase

# ---------------------------------------------------------------------------------------------------------- Daniel Reyes
DANIEL_PROFILE = """EXPERIENCE:
- Science Teacher at Fox Valley Middle School (2014 – 2025)
  * Planned and taught five sections a day of grades 6 to 8 science.
  * Built a year-long project-based curriculum used by four other teachers.
  * Recorded 60 short lesson videos during remote learning and shared them in Google Classroom.
  * Mentored two student teachers.
  * Skill: Screencastify
- Summer Camp Counselor at Riverbend Outdoor Camp (2010 – 2013)

SKILLS (not tied to one specific role):
- Curriculum design
- Assessment writing
- Google Classroom
- Canvas LMS
- Classroom management

EDUCATION:
- Western Illinois University: M.Ed., Curriculum and Instruction (2016)
- Eastern Illinois University: B.S., Biology (2010)
"""
DANIEL_FACT = {"category": "Pilot sessions", "bullet_text": "Piloted a new project-based science unit with one seventh-grade section before full rollout, using pre- and post-tests to measure learning gains and tracking scores in a Google Sheets gradebook."}
DANIEL_HISTORY = [
    {"id": "q1", "category": "Articulate Storyline (preferred)", "type": "yes_no", "answer": "no",
     "question": "Have you used Articulate Storyline or Articulate Rise to build any e-learning modules?"},
    {"id": "q2", "category": "Pilot sessions (required)", "type": "yes_no", "answer": "yes",
     "question": "Have you ever piloted a new lesson, course, or training program and formally measured its results or effectiveness?"},
    {"id": "q3", "category": "Subject matter experts (required)", "type": "yes_no", "answer": "no",
     "question": "Have you worked directly with a non-teaching expert (such as a specialist or professional outside education) to turn their knowledge into instructional content?"},
    {"id": "q4", "category": "ADDIE or SAM (preferred)", "type": "yes_no", "answer": "no",
     "question": "Are you familiar with or have you applied the ADDIE or SAM instructional design models?"},
    {"id": "q5", "category": "Corporate training (preferred)", "type": "yes_no", "answer": "no",
     "question": "Have you designed or delivered training for a corporate or business audience, as opposed to K-12 students?"},
    {"id": "q6", "category": "Video editing (preferred)", "type": "yes_no", "answer": "no",
     "question": "Have you used video editing software (beyond simple screen recording) to produce or edit training videos?"},
    {"id": "q7", "category": "Mentoring", "type": "yes_no", "answer": "skip",
     "question": "Have you led a formal mentoring program for new hires?"},
]
DANIEL_DENIALS = denials_from_history(DANIEL_HISTORY)

# What the live site returned for this candidate before the fix (resume version 30), reduced to the parts that matter.
DANIEL_BEFORE = {
    "name": "Daniel Reyes", "contact": "Aurora, IL | (630) 555-0112 | daniel.reyes@example.com",
    "headline": "Instructional Design | Curriculum & Assessment Development | Learning Technology",
    "summary": ("Educator with over 10 years of teaching experience, bringing strong instructional design skills to engaging, outcomes-focused learning content. "
                "Built a year-long project-based curriculum adopted by four other teachers, produced e-learning modules for remote learning, and ran pilot sessions using pre/post-tests to measure results. "
                "Works closely with subject matter experts to translate complex content into effective lessons. "
                "Comfortable with video editing using Screencastify to support instruction."),
    "skills": ["Instructional Design & Content: Instructional Design, Curriculum Design, Assessment Writing, Project-Based Learning, Learning Needs Analysis",
               "Delivery & Technology: E-Learning Modules, LMS, Google Classroom, Canvas LMS, Screencastify, Video Editing, Remote Learning",
               "Program Execution: Pilot Sessions, Measuring Results, Teaching, Classroom Management, Mentoring",
               "Collaboration: Subject Matter Experts, Writing, Stakeholder Collaboration"],
    "experience": [{"title": "Science Teacher", "subtitle": "Fox Valley Middle School — 2014 – 2025", "bullets": [
        "Planned and taught five sections a day of grades 6–8 science, applying strong writing and instructional design skills to daily lesson development.",
        "Built a year-long project-based curriculum grounded in learning needs analysis, later adopted and used by four other teachers.",
        "Piloted a new project-based science unit with one seventh-grade section before full rollout, using pre- and post-tests to measure student learning gains and tracking results in a Google Sheets gradebook.",
        "Recorded 60 short e-learning modules using Screencastify during remote learning. Shared them in Google Classroom and applied video editing skills to support independent study.",
        "Mentored two student teachers as a subject matter resource and collaborated with fellow teachers on curriculum implementation."]}],
    "education": ["Western Illinois University: M.Ed., Curriculum and Instruction (2016)", "Eastern Illinois University: B.S., Biology (2010)"],
    "certifications": [],
}
# A planner that follows the new rules (what the model is now told to do), for the Instructional Designer posting.
DANIEL_PLAN = [
    {"term": "instructional design", "importance": "required", "kind": "skill", "support": "related", "evidence": "Built a year-long project-based curriculum used by four other teachers"},
    {"term": "learning needs analysis", "importance": "required", "kind": "skill", "support": "related", "evidence": "Planned curriculum for grades 6-8 science"},
    {"term": "pilot sessions", "importance": "required", "kind": "skill", "support": "related", "evidence": "Piloted a new unit with one seventh-grade section (confirmed)"},
    {"term": "measuring results", "importance": "required", "kind": "skill", "support": "related", "evidence": "pre- and post-tests (confirmed)"},
    {"term": "LMS", "importance": "required", "kind": "skill", "support": "literal", "evidence": "Canvas LMS"},
    {"term": "e-learning modules", "importance": "required", "kind": "skill", "support": "none", "evidence": ""},
    {"term": "subject matter experts", "importance": "required", "kind": "skill", "support": "none", "evidence": ""},
    {"term": "video editing", "importance": "preferred", "kind": "skill", "support": "related", "evidence": "Recorded 60 short lesson videos with Screencastify"},  # the loose answer the model gave live
    {"term": "Articulate Storyline", "importance": "preferred", "kind": "skill", "support": "none", "evidence": ""},
    {"term": "corporate training", "importance": "preferred", "kind": "skill", "support": "related", "evidence": "Taught five sections a day"},  # loose answer
    {"term": "classroom collaboration", "importance": "mentioned", "kind": "skill", "support": "related", "evidence": "Curriculum used by four other teachers"},
]
# The edit pass doing what the flagged items ask: the unsupported claims out, what the candidate really did kept.
DANIEL_AFTER_EDIT = copy.deepcopy(DANIEL_BEFORE)
DANIEL_AFTER_EDIT["summary"] = ("Educator with over 10 years of teaching experience. Built a year-long project-based curriculum adopted by four other teachers, "
                                "recorded 60 short lesson videos for remote learning, and piloted a new unit using pre/post-tests to measure results.")
DANIEL_AFTER_EDIT["experience"][0]["bullets"] = [
    "Planned and taught five sections a day of grades 6–8 science.",
    "Built a year-long project-based curriculum, later adopted and used by four other teachers.",
    DANIEL_BEFORE["experience"][0]["bullets"][2],
    "Recorded 60 short lesson videos during remote learning and shared them in Google Classroom.",
    "Mentored two student teachers and worked with fellow teachers on curriculum implementation."]
DANIEL_AFTER_EDIT["headline"] = "Instructional Design | Curriculum & Assessment Development"

# ------------------------------------------------------------------------------------------------- Sears cashier to bank teller
SEARS_PROFILE = """EXPERIENCE:
- Cashier at Sears (2019 – 2024)
  * Processed customer purchases.
  * Handled cash payments.
  * Assisted customers.
  * Resolved basic customer concerns.
"""
SEARS_POSTING = ("Bank Teller. Process deposits, withdrawals and payments accurately; handle cash; provide friendly customer service; resolve customer concerns; "
                 "service bank accounts; follow regulatory banking compliance; reconcile the cash drawer at end of shift; refer financial products.")
SEARS_PLAN = [
    {"term": "customer service", "importance": "required", "kind": "skill", "support": "transferable", "evidence": "Cashier at Sears: assisted customers and resolved basic customer concerns"},
    {"term": "cash handling", "importance": "required", "kind": "skill", "support": "transferable", "evidence": "Cashier at Sears: handled cash payments"},
    {"term": "transaction processing", "importance": "required", "kind": "skill", "support": "transferable", "evidence": "Cashier at Sears: processed customer purchases"},
    {"term": "problem resolution", "importance": "required", "kind": "skill", "support": "transferable", "evidence": "Cashier at Sears: resolved basic customer concerns"},
    {"term": "bank account servicing", "importance": "required", "kind": "skill", "support": "none", "evidence": ""},
    {"term": "regulatory banking compliance", "importance": "required", "kind": "skill", "support": "none", "evidence": ""},
    {"term": "cash drawer reconciliation", "importance": "required", "kind": "skill", "support": "none", "evidence": ""},
    {"term": "financial product sales", "importance": "preferred", "kind": "skill", "support": "none", "evidence": ""},
]
SEARS_GOOD = {
    "name": "Sam Ortiz", "contact": "Chicago, IL | sam@example.com", "headline": "Customer Service | Cash Handling | Transaction Accuracy",
    "summary": "Customer-focused retail professional with five years of experience processing transactions and handling cash payments.",
    "skills": ["Customer Service: Customer Service, Problem Resolution", "Transactions: Cash Handling, Transaction Processing"],
    "experience": [{"title": "Cashier", "subtitle": "Sears — 2019 – 2024", "bullets": [
        "Processed customer transactions, handled cash payments, and assisted customers with routine inquiries and concerns."]}],
    "education": [], "certifications": [],
}
SEARS_BAD = copy.deepcopy(SEARS_GOOD)
SEARS_BAD["summary"] = "Banking professional who managed customer bank accounts and ensured regulatory banking compliance."
SEARS_BAD["skills"] = ["Banking: Bank Account Servicing, Regulatory Banking Compliance, Cash Drawer Reconciliation", "Customer Service: Customer Service, Problem Resolution"]
SEARS_BAD["experience"][0]["bullets"] = ["Managed customer bank accounts, performed regulated banking transactions, and ensured financial compliance.",
                                         "Reconciled the cash drawer at the end of every shift."]


def fake_ai(plan=None, built=None, edited=None, fail_edit=False, seen=None):
    """Stands in for job_match._call_with_retry: returns fixed answers by call name and records the prompts it was sent."""
    def call(name, system, user, tool, extract=None):
        if seen is not None:
            seen[name] = {"system": system, "user": user}
        if name == "career_term_plan":
            return {"terms": copy.deepcopy(plan)}
        if name == "career_job_build_resume":
            return {"resume_data": copy.deepcopy(built)}
        if name in ("career_readability_fix", "career_term_revise"):
            if fail_edit or edited is None:
                raise JobMatchError("edit unavailable")
            return {"resume_data": copy.deepcopy(edited)}
        raise AssertionError("unexpected AI call " + name)
    return call


def run(profile, posting, plan, built, history=None, facts=None, edited=None, fail_edit=False):
    seen = {}
    with mock.patch.object(job_match, "_call_with_retry", fake_ai(plan, built, edited, fail_edit, seen)):
        result = build_checked_resume(profile, posting, facts or [], "N", "c@example.com", denials_from_history(history or []))
    return result, seen


def skills_text(resume):
    return " | ".join(resume["skills"]).lower()


def prose(resume):
    return " ".join([resume.get("summary", ""), resume.get("headline", "")] + [b for j in resume["experience"] for b in j["bullets"]]).lower()


# ====================================================================================================== negative answers
class NegativeAnswerPropagation(unittest.TestCase):
    def test_only_explicit_no_answers_become_denials(self):
        self.assertEqual(len(DANIEL_DENIALS), 5)  # q1, q3, q4, q5, q6; the yes (q2) and the skipped q7 are not denials
        self.assertFalse(any("mentoring" in d["question"].lower() for d in DANIEL_DENIALS))

    def test_a_skipped_or_detail_answer_is_never_a_denial_or_a_confirmation(self):
        history = [{"question": "Q one?", "answer": "skip", "type": "yes_no"}, {"question": "Q two?", "answer": "no", "type": "detail"},
                   {"question": "Q three?", "answer": "", "type": "yes_no"}, "junk", None]
        self.assertEqual(denials_from_history(history), [])
        self.assertEqual(denials_from_history(None), [])

    def test_the_planner_is_shown_the_questions_the_candidate_denied(self):
        seen = {}
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(plan=DANIEL_PLAN, seen=seen)):
            plan_terms(DANIEL_PROFILE, "(none)", "posting", DANIEL_DENIALS)
        user = seen["career_term_plan"]["user"]
        self.assertIn("Have you used video editing software", user)
        self.assertNotIn("formal mentoring program", user)  # a skipped question is not listed

    def test_the_writer_is_shown_the_denials_and_the_transferable_terms(self):
        seen = {}
        plan = DANIEL_PLAN + [{"term": "lesson planning", "importance": "mentioned", "kind": "skill", "support": "transferable", "evidence": "Planned and taught five sections"}]
        run(DANIEL_PROFILE, "posting", plan, DANIEL_BEFORE, history=DANIEL_HISTORY, edited=DANIEL_AFTER_EDIT)
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(plan=plan, built=DANIEL_BEFORE, edited=DANIEL_AFTER_EDIT, seen=seen)):
            build_checked_resume(DANIEL_PROFILE, "posting", [], "N", "c", DANIEL_DENIALS)
        user = seen["career_job_build_resume"]["user"]
        self.assertIn("EXPLICITLY SAID NO", user)
        self.assertIn("Have you worked directly with a non-teaching expert", user)
        self.assertIn("lesson planning  (the candidate's real activity: Planned and taught five sections)", user)


class ScopedDenials(unittest.TestCase):
    def test_a_denied_activity_is_not_supported_whatever_the_model_said(self):
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(plan=DANIEL_PLAN)):
            terms = {t["term"]: t for t in plan_terms(DANIEL_PROFILE, "(none)", "posting", DANIEL_DENIALS)}
        self.assertEqual(terms["video editing"]["support"], "none")  # the model said "related"; the candidate said no
        self.assertTrue(terms["video editing"]["denied"])
        self.assertEqual(terms["corporate training"]["support"], "none")
        self.assertEqual(terms["Articulate Storyline"]["support"], "none")

    def test_genuinely_evidenced_adjacent_terms_are_not_removed_by_a_word_in_common(self):
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(plan=DANIEL_PLAN)):
            terms = {t["term"]: t for t in plan_terms(DANIEL_PROFILE, "(none)", "posting", DANIEL_DENIALS)}
        for kept in ("instructional design", "pilot sessions", "measuring results", "classroom collaboration", "LMS"):
            self.assertNotEqual(terms[kept]["support"], "none", kept)
        self.assertIsNone(denied_by("classroom collaboration", DANIEL_DENIALS))
        self.assertIsNone(denied_by("collaboration", DANIEL_DENIALS))  # one-word terms are never decided by the guard
        self.assertIsNone(denied_by("screen recording", DANIEL_DENIALS))  # "beyond simple screen recording" is the contrast, not the denial
        self.assertIsNone(denied_by("lesson videos", DANIEL_DENIALS))

    def test_a_no_to_corporate_experts_does_not_erase_collaboration_with_classroom_teachers(self):
        denials = denials_from_history([{"question": "Have you collaborated with corporate subject matter experts?", "answer": "no", "type": "yes_no", "category": ""}])
        self.assertIsNotNone(denied_by("corporate subject matter experts", denials))
        self.assertIsNone(denied_by("classroom teacher collaboration", denials))
        self.assertIsNone(denied_by("collaborating with classroom teachers", denials))

    def test_transferable_and_related_support_need_a_stated_reason(self):
        plan = [{"term": "customer service", "importance": "required", "kind": "skill", "support": "transferable", "evidence": ""},
                {"term": "data entry", "importance": "required", "kind": "skill", "support": "related", "evidence": ""},
                {"term": "made up tier", "importance": "required", "kind": "skill", "support": "bogus", "evidence": "x"}]
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(plan=plan)):
            terms = plan_terms(SEARS_PROFILE, "(none)", "posting", [])
        self.assertEqual([t["support"] for t in terms], ["none", "none", "none"])

    def test_prompts_define_related_strictly_and_add_the_transferable_tier(self):
        plan_prompt = term_pipeline.PLAN_SYSTEM_PROMPT
        self.assertIn("RELATED MEANS THE SAME ACTIVITY IN OTHER WORDS", plan_prompt)
        self.assertIn("a lesson video is not an e-learning module", plan_prompt)
        self.assertIn('"transferable"', plan_prompt)
        self.assertIn("skipped or unanswered question is NOT evidence", plan_prompt)
        self.assertIn("does not erase evidence of collaborating with classroom teachers", plan_prompt)


class Conflicts(unittest.TestCase):
    def test_a_fact_that_repeats_a_denial_is_reported_and_held_back_not_silently_used(self):
        fact = {"category": "Video editing", "bullet_text": "Edited training videos with video editing software."}
        conflicts = find_conflicts(DANIEL_DENIALS, [fact, DANIEL_FACT])
        self.assertEqual([c["fact"] for c in conflicts], [fact["bullet_text"]])
        seen = {}
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(DANIEL_PLAN, DANIEL_AFTER_EDIT, DANIEL_AFTER_EDIT, seen=seen)):
            result = build_checked_resume(DANIEL_PROFILE, "posting", [fact, DANIEL_FACT], "N", "c", DANIEL_DENIALS)
        self.assertEqual(len(result["answer_conflicts"]), 1)
        self.assertNotIn("Edited training videos", seen["career_job_build_resume"]["user"])
        self.assertIn("Piloted a new project-based science unit", seen["career_job_build_resume"]["user"])  # the non-conflicting confirmed fact is kept

    def test_a_previously_confirmed_fact_is_not_removed_by_an_unrelated_denial(self):
        teachers = {"bullet_text": "Collaborated with fellow teachers to adapt the curriculum for four classrooms."}
        self.assertEqual(find_conflicts(DANIEL_DENIALS, [teachers, DANIEL_FACT]), [])


# =============================================================================================== Daniel Reyes, before and after
class DanielReyes(unittest.TestCase):
    def test_before_the_fix_the_resume_contradicted_the_candidate(self):
        # The recorded live output: every unsupported claim named in Finding 2 is present.
        self.assertIn("video editing", prose(DANIEL_BEFORE))
        self.assertIn("e-learning modules", prose(DANIEL_BEFORE))
        self.assertIn("subject matter experts", prose(DANIEL_BEFORE))
        self.assertIn("stakeholder collaboration", skills_text(DANIEL_BEFORE))

    def test_unsupported_and_denied_claims_are_removed_and_the_genuine_experience_stays(self):
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, DANIEL_BEFORE, DANIEL_HISTORY, [DANIEL_FACT], edited=DANIEL_AFTER_EDIT)
        resume = result["resume_data"]
        text, skills = prose(resume), skills_text(resume)
        for gone in ("video editing", "e-learning modules", "subject matter expert", "stakeholder collaboration", "corporate training", "articulate"):
            self.assertNotIn(gone, text + " " + skills, gone)
        # what the candidate really did is still there, in plain professional wording
        self.assertIn("60 short lesson videos", text)
        self.assertIn("google classroom", text)
        self.assertIn("project-based curriculum", text)
        self.assertIn("pre- and post-tests", text)
        self.assertIn("mentored two student teachers", text)
        for kept in ("instructional design", "pilot sessions", "measuring results", "screencastify", "canvas lms", "curriculum design", "assessment writing"):
            self.assertIn(kept, skills, kept)
        self.assertEqual(result["claim_review"], [])

    def test_skills_are_cleaned_by_code_even_when_the_edit_pass_is_unavailable(self):
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, DANIEL_BEFORE, DANIEL_HISTORY, [DANIEL_FACT], fail_edit=True)
        skills = skills_text(result["resume_data"])
        for gone in ("video editing", "e-learning modules", "subject matter experts", "stakeholder collaboration"):
            self.assertNotIn(gone, skills, gone)
        self.assertIn("pilot sessions", skills)
        # the prose claims it could not fix are REPORTED, never hidden
        problems = " ".join(i["text"].lower() for i in result["claim_review"])
        self.assertIn("e-learning modules", problems)
        self.assertIn("subject matter experts", problems)
        self.assertIn("video editing", problems)
        self.assertEqual(set(result["skills_removed"]) >= {"Video Editing", "E-Learning Modules", "Subject Matter Experts", "Stakeholder Collaboration"}, True)

    def test_skipped_keywords_are_not_forced_into_the_output(self):
        result, seen = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, DANIEL_AFTER_EDIT, DANIEL_HISTORY, [DANIEL_FACT], edited=DANIEL_AFTER_EDIT)
        self.assertNotIn("Articulate Storyline", " ".join(result["resume_data"]["skills"]))
        statuses = {r["term"]: r["status"] for r in result["term_report"]}
        self.assertEqual(statuses["Articulate Storyline"], "not_in_profile")  # stays an honest gap the candidate can see
        self.assertEqual(statuses["video editing"], "not_in_profile")

    def test_a_correction_that_removes_an_unsupported_term_is_accepted(self):
        # The edit pass used to be rejected for "losing" any planned term; losing an UNSUPPORTED one is the point.
        with mock.patch.object(job_match, "_call_with_retry", fake_ai(edited=DANIEL_AFTER_EDIT)):
            resume, info = term_pipeline.improve_readability(copy.deepcopy(DANIEL_BEFORE), DANIEL_PROFILE, [
                {"term": t["term"], "kind": t["kind"], "importance": t["importance"], "support": t["support"], "evidence": t["evidence"]}
                for t in DANIEL_PLAN if t["support"] != "related" or t["term"] in ("instructional design", "pilot sessions", "measuring results")],
                ["video editing", "e-learning modules", "subject matter experts", "Articulate Storyline"])
        self.assertTrue(info["edited"], info)
        self.assertNotIn("e-learning modules", prose(resume))


# ============================================================================================= Sears cashier to bank teller
class SearsCashierToBankTeller(unittest.TestCase):
    def test_confirmed_cash_handling_and_customer_service_are_kept_and_highlighted(self):
        result, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, SEARS_GOOD, edited=SEARS_GOOD)
        resume = result["resume_data"]
        skills = skills_text(resume)
        for kept in ("customer service", "cash handling", "transaction processing", "problem resolution"):
            self.assertIn(kept, skills, kept)
        self.assertIn("handled cash payments", prose(resume))
        self.assertIn("assisted customers", prose(resume))
        self.assertEqual(result["skills_removed"], [])
        self.assertEqual(result["claim_review"], [])

    def test_banking_duties_and_register_balancing_are_not_invented(self):
        fixed = copy.deepcopy(SEARS_GOOD)  # the edit pass keeps the same number of bullets: the invented ones are rewritten in place
        fixed["experience"][0]["bullets"].append("Assisted customers and resolved basic concerns at the register.")
        result, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, SEARS_BAD, edited=fixed)
        resume = result["resume_data"]
        skills, text = skills_text(resume), prose(resume)
        for gone in ("bank account servicing", "regulatory banking compliance", "cash drawer reconciliation", "managed customer bank accounts", "regulated banking", "financial compliance", "reconciled the cash drawer"):
            self.assertNotIn(gone, skills + " " + text, gone)
        self.assertIn("customer service", skills)  # the genuine skills survive the cleanup
        self.assertIn("problem resolution", skills)

    def test_when_the_edit_pass_is_unavailable_the_unsupported_claims_are_still_reported(self):
        result, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, SEARS_BAD, fail_edit=True)
        skills = skills_text(result["resume_data"])
        self.assertNotIn("bank account servicing", skills)
        self.assertNotIn("cash drawer reconciliation", skills)
        self.assertIn("customer service", skills)
        reported = " ".join(i["text"].lower() for i in result["claim_review"])
        self.assertIn("regulatory banking compliance", reported)  # named in the summary
        gaps = [r["term"] for r in result["term_report"] if r["status"] == "not_in_profile"]
        self.assertIn("bank account servicing", gaps)  # still visible as a gap, not claimed
        self.assertIn("cash drawer reconciliation", gaps)

    def test_the_gap_interview_is_told_to_ask_a_targeted_question_not_to_assume_register_balancing(self):
        prompt = job_match.COMPARE_SYSTEM_PROMPT
        self.assertIn("Did you count or reconcile your cash register at the end of your shifts?", prompt)
        self.assertIn("simply working in a role does not prove every duty of it", prompt)
        self.assertIn("a skipped question is never evidence", prompt)
        self.assertIn("never around what they lack", prompt)

    def test_the_writer_is_told_the_posting_is_relevance_not_facts_and_to_keep_the_candidates_wording(self):
        prompt = job_match.BUILD_RESUME_SYSTEM_PROMPT
        for clause in ("SOURCE OF RELEVANCE, NEVER OF FACTS ABOUT THE CANDIDATE", "Accurate meaning always wins over exact keyword insertion",
                       "never rename what they did", "REAL BUT DIFFERENT activity", "Do not mechanically insert every keyword",
                       "ONLY where that sentence already describes the same activity", "never for a more specialised one"):
            self.assertIn(clause, prompt, clause)
        self.assertNotIn("it is AUTHORITATIVE - every term on it must appear", prompt)

    def test_a_cashier_role_with_no_description_gets_no_invented_bullets(self):
        bare = copy.deepcopy(SEARS_GOOD)
        out, emptied = resume_quality.drop_unsourced_bullets(bare, [{"title": "Cashier", "organization": "Sears", "has_source": False}])
        self.assertEqual(emptied, ["Cashier"])
        self.assertEqual(out["experience"][0]["bullets"], [])


# ====================================================================================================== edge cases
class EdgeCases(unittest.TestCase):
    def test_unsupported_specialised_software_is_removed_from_skills_and_flagged_in_prose(self):
        resume = copy.deepcopy(SEARS_GOOD)
        resume["skills"].append("Tools: Articulate Storyline, Excel")
        resume["experience"][0]["bullets"].append("Built courses in Articulate Storyline.")
        terms = [{"term": "Articulate Storyline", "kind": "skill", "importance": "preferred", "support": "none", "evidence": ""}] + SEARS_PLAN
        cleaned, removed = sanitize_skills(resume, terms, SEARS_PROFILE)
        self.assertIn("Articulate Storyline", removed)
        self.assertNotIn("articulate", skills_text(cleaned))
        self.assertTrue(find_claim_issues(resume, ["Articulate Storyline"]))

    def test_a_genuine_skill_in_different_words_is_not_removed(self):
        resume = dict(SEARS_GOOD, skills=["Customer Support: Customer Assistance, Issue Resolution, Handling Cash"])
        cleaned, removed = sanitize_skills(resume, [], SEARS_PROFILE)  # no plan at all: traced to the evidence by word stems
        self.assertEqual(removed, [])
        self.assertIn("Issue Resolution", cleaned["skills"][0])

    def test_a_skill_with_nothing_in_the_evidence_is_removed(self):
        resume = dict(SEARS_GOOD, skills=["Core: Customer Service, Blockchain Forensics"])
        cleaned, removed = sanitize_skills(resume, [], SEARS_PROFILE)
        self.assertEqual(removed, ["Blockchain Forensics"])
        self.assertEqual(cleaned["skills"], ["Core: Customer Service"])

    def test_a_skill_that_is_a_supported_term_stays_even_if_the_wording_is_new(self):
        resume = dict(SEARS_GOOD, skills=["Core: Transaction Accuracy"])
        terms = [{"term": "transaction accuracy", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "Cashier at Sears: processed customer purchases"}]
        cleaned, removed = sanitize_skills(resume, terms, SEARS_PROFILE)
        self.assertEqual(removed, [])

    def test_candidate_supplied_figures_pass_and_invented_ones_are_flagged(self):
        resume = {"summary": "", "headline": "", "skills": [], "education": [], "experience": [{"title": "Teacher", "subtitle": "S", "bullets": [
            "Recorded 60 short lesson videos.", "Recorded 240 short lesson videos and raised scores by 35%."]}]}
        issues = resume_quality.find_issues(resume, DANIEL_PROFILE, [], term_pipeline.term_in_text, "", today_year=2026)
        flagged = " ".join(i["problem"] for i in issues)
        self.assertIn('"240"', flagged)
        self.assertIn('"35"', flagged)
        self.assertNotIn('"60"', flagged)

    def test_a_career_changer_keeps_real_experience_and_loses_only_the_unsupported_labels(self):
        result, _ = run(DANIEL_PROFILE, "posting", DANIEL_PLAN, DANIEL_AFTER_EDIT, DANIEL_HISTORY, [DANIEL_FACT], edited=DANIEL_AFTER_EDIT)
        self.assertEqual(len(result["resume_data"]["experience"][0]["bullets"]), 5)  # no bullet dropped
        self.assertEqual(result["resume_data"]["education"], DANIEL_BEFORE["education"])

    def test_the_planning_failure_fallback_still_cleans_skills(self):
        def call(name, system, user, tool, extract=None):
            if name == "career_term_plan":
                raise JobMatchError("planner down")
            return {"resume_data": copy.deepcopy(SEARS_BAD)}
        with mock.patch.object(job_match, "_call_with_retry", call):
            result = build_checked_resume(SEARS_PROFILE, SEARS_POSTING, [], "N", "c", [])
        self.assertNotIn("blockchain", skills_text(result["resume_data"]))
        self.assertEqual(result["term_report"], [])
        self.assertIn("answer_conflicts", result)


# ================================================================================================================== route
class RouteCarriesTheAnswers(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}),
                        mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()

    def test_the_build_route_passes_the_no_answers_to_the_pipeline(self):
        self.onboard(self.a)
        captured = {}

        def fake_build(profile_text, job_description, confirmed_facts, name, contact, denials):
            captured["denials"] = denials
            return {"resume_data": copy.deepcopy(SEARS_GOOD), "role_selection": [], "term_report": [], "ats_match": None,
                    "answer_conflicts": [], "claim_review": [], "skills_removed": []}

        with mock.patch("career.routes.build_checked_resume", fake_build):
            res = self.call("POST", "/job-build-resume", self.a, json={
                "job_description": "Instructional Designer at Brightpath Learning Solutions. Writes storyboards and builds e-learning in Articulate Storyline.",
                "name": "Daniel Reyes", "contact": "Aurora, IL | d@example.com", "confirmed_facts": [], "qa_history": DANIEL_HISTORY})
        self.assertEqual(res.status_code, 200, res.text)
        questions = [d["question"] for d in captured["denials"]]
        self.assertEqual(len(questions), 5)
        self.assertTrue(any("video editing software" in q for q in questions))
        self.assertFalse(any("mentoring program" in q for q in questions))  # skipped, not denied
        body = res.json()
        self.assertEqual(body["answer_conflicts"], [])
        self.assertEqual(body["claim_review"], [])


if __name__ == "__main__":
    unittest.main()


class TransferableIsShownAsRelevantNotAsAGap(unittest.TestCase):
    def test_a_transferable_term_is_reported_as_transferable_until_it_really_appears_on_the_resume(self):
        result, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, SEARS_GOOD, edited=SEARS_GOOD)
        status = {r["term"]: r["status"] for r in result["term_report"]}
        self.assertEqual(status["customer service"], "on_resume")  # the candidate's own skill, present on the resume
        self.assertEqual(status["bank account servicing"], "not_in_profile")  # an honest gap
        plain = copy.deepcopy(SEARS_GOOD)
        plain["headline"], plain["summary"] = "Customer Service", "Retail professional."
        plain["skills"] = ["Customer Service: Customer Service"]
        plain["experience"][0]["bullets"] = ["Processed customer purchases."]
        result2, _ = run(SEARS_PROFILE, SEARS_POSTING, SEARS_PLAN, plain, edited=plain)
        status2 = {r["term"]: r["status"] for r in result2["term_report"]}
        self.assertEqual(status2["cash handling"], "transferable")  # relevant experience to build on, not a "missing" item

    def test_the_page_lists_transferable_terms_with_encouraging_wording_and_no_add_button(self):
        import pathlib
        js = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "career" / "js" / "jobMatch.js").read_text(encoding="utf-8")
        self.assertIn('r.status === "transferable"', js)
        self.assertIn("your experience may be relevant", js)
        self.assertIn("related to experience you already have", js)
