"""Priority 1, PR-2: where each statement on a finished resume came from. A bullet is compared with the saved entry of its OWN role, the summary and
Skills with the plan. A line the candidate's history does not state is put back to their own sentence for that role, or left out, and reported;
nothing is rewritten by a model. Built on the fictional Marcus Bell live run of 2026-11-06 (the writer wove posting vocabulary into bullets and
borrowed phrases from other roles). Saved data, stand-in AI, no live calls.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import copy
import os
import unittest
from unittest import mock

import abuse_guard
from career import job_match, provenance, term_pipeline
from models import ResumeVersion
from tests.test_ownership import SUB_A, OwnershipTestCase

PROFILE = """EXPERIENCE:
- Shift Lead at Hearthside Home Goods (2021 – Present)
  * Opened and closed the store and kept the daily cash count accurate
  * Scheduled 6 associates each week
  * Handled returns and customer complaints, about 20 a week
  * Trained new hires on the POS system and store procedures
  * Counted inventory weekly
- Sales Associate at Hearthside Home Goods (2016 – 2021)
  * Helped customers choose products and explained features
  * Processed purchases and returns on the POS system
  * Resolved upset customers calmly using de-escalation
- Call Centre Agent (part-time) at Brightline Direct (2015 – 2016)
  * Took inbound customer orders by phone for 4 months
  * Confirmed order details and answered delivery questions

SKILLS (not tied to one specific role):
- Scheduling
- De-escalation
- POS systems

EDUCATION:
- Westfield High School: High School Diploma (2014)

CERTIFICATIONS:
- Customer Service Fundamentals — Online course (2023)"""

POSTING = ("Customer Success Associate (SaaS)\nRun onboarding calls with new customers, answer customer questions in writing, resolve support cases in our "
           "ticketing software, keep customers happy during renewals and calm upset customers with de-escalation. Salesforce or HubSpot or a similar CRM. "
           "A customer service certificate (for example Customer Service Fundamentals) or equivalent customer-facing experience. Strong written "
           "communication. SaaS experience is a plus. Scheduling calls and managing your own calendar.")

WRITER_OUTPUT = {
    "name": "Marcus Bell", "contact": "Naperville, IL | marcus.bell@example.com", "headline": "Customer Service Professional",
    "summary": ("Customer-facing professional with experience across retail sales, shift leadership, and phone-based order support. "
                "Well suited to a customer success environment focused on customer service."),
    "skills": ["Customer Service: Customer Service, Customer Success, Customer Service Certificate, De-escalation",
               "Operations & Tools: POS Systems, Scheduling, Phone Communication"],
    "experience": [
        {"title": "Shift Lead", "subtitle": "Hearthside Home Goods — 2021 – Present", "bullets": [
            "Opened and closed the store and kept the daily cash count accurate",
            "Scheduled 6 associates each week, coordinating shift coverage and calendars",
            "Handled returns and customer complaints, about 20 a week, using de-escalation to calm upset customers",
            "Trained new hires on the POS system and store procedures",
            "Counted inventory weekly"]},
        {"title": "Sales Associate", "subtitle": "Hearthside Home Goods — 2016 – 2021", "bullets": [
            "Helped customers choose products and explained features, building rapport to support customer service",
            "Processed purchases and returns on the POS system",
            "Resolved upset customers calmly using de-escalation, answering customer questions and handling complaints"]},
        {"title": "Call Centre Agent (part-time)", "subtitle": "Brightline Direct — 2015 – 2016", "bullets": [
            "Took inbound customer orders by phone for 4 months",
            "Confirmed order details and answered delivery questions"]},
    ],
    "education": ["Westfield High School: High School Diploma (2014)"], "certifications": ["Customer Service Fundamentals — Online course (2023)"],
}

PLAN = [
    {"term": "customer success", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "customer-facing roles"},
    {"term": "customer service certificate", "kind": "skill", "importance": "required", "support": "related", "evidence": "Certifications: Customer Service Fundamentals (2023)."},
    {"term": "de-escalation", "kind": "skill", "importance": "required", "support": "literal", "evidence": "Skills list: De-escalation"},
    {"term": "phone communication", "kind": "skill", "importance": "mentioned", "support": "related", "evidence": "Call Centre Agent: took inbound customer orders by phone"},
    {"term": "customer service", "kind": "skill", "importance": "required", "support": "literal", "evidence": "Certification: Customer Service Fundamentals"},
    {"term": "ticketing software", "kind": "skill", "importance": "required", "support": "none", "evidence": ""},
    {"term": "Salesforce", "kind": "skill", "importance": "required", "support": "none", "evidence": ""},
]


def audit(resume=None, terms=PLAN, profile=PROFILE, facts=""):
    return provenance.audit_and_repair(copy.deepcopy(resume or WRITER_OUTPUT), profile, POSTING, facts, "Customer Success Associate", terms)


def bullets(resume, title):
    return next(j["bullets"] for j in resume["experience"] if j["title"] == title)


class A_ParsingTheProfile(unittest.TestCase):
    def test_roles_are_separated_with_their_own_sentences(self):
        roles, general = provenance.parse_profile(PROFILE)
        self.assertEqual([(r["title"], r["organization"], len(r["sentences"])) for r in roles],
                         [("Shift Lead", "Hearthside Home Goods", 5), ("Sales Associate", "Hearthside Home Goods", 3), ("Call Centre Agent (part-time)", "Brightline Direct", 2)])
        self.assertIn("De-escalation", general)
        self.assertIn("Customer Service Fundamentals", general)
        self.assertNotIn("Scheduled 6 associates", general)

    def test_a_role_skill_line_counts_as_that_roles_evidence(self):
        text = "EXPERIENCE:\n- Shift Lead at Acme (2021)\n  * Scheduled staff\n  * Skill: Coaching — coached two new leads\n\nSKILLS (not tied to one specific role):\n(none recorded yet)"
        roles, _ = provenance.parse_profile(text)
        self.assertIn("coached", roles[0]["text"])


class B_BulletsAreCheckedAgainstTheirOwnRole(unittest.TestCase):
    def test_the_four_marcus_bullets_are_put_back_to_his_own_sentences(self):
        out, report = audit()
        self.assertEqual(bullets(out, "Shift Lead"), ["Opened and closed the store and kept the daily cash count accurate", "Scheduled 6 associates each week",
                                                    "Handled returns and customer complaints, about 20 a week", "Trained new hires on the POS system and store procedures", "Counted inventory weekly"])
        self.assertEqual(bullets(out, "Sales Associate"), ["Helped customers choose products and explained features", "Processed purchases and returns on the POS system",
                                                         "Resolved upset customers calmly using de-escalation"])
        self.assertEqual(len(report["restored"]), 4)
        self.assertEqual(report["held"][0]["where"], "summary")  # only the summary positioning line is held, no bullet

    def test_the_reasons_name_the_posting_or_the_role_the_words_came_from(self):
        _, report = audit()
        why = {r["before"]: r["basis"] for r in report["restored"]}
        by_start = lambda start: next(v for k, v in why.items() if k.startswith(start))
        self.assertIn("posting's wording", by_start("Scheduled 6 associates each week, c"))
        self.assertIn("Sales Associate role", by_start("Handled returns and customer complaints,"))
        self.assertIn("Call Centre Agent (part-time) and Shift Lead role", by_start("Resolved upset customers calmly using "))
        self.assertIn("posting's wording", by_start("Helped customers choose products an"))

    def test_cross_role_borrowing_is_found_in_both_directions(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        bullets(resume, "Call Centre Agent (part-time)").append("Scheduled 6 associates each week")  # a Shift Lead sentence under another role
        out, report = audit(resume)
        self.assertNotIn("Scheduled 6 associates each week", bullets(out, "Call Centre Agent (part-time)"))
        self.assertTrue(any("Shift Lead role" in r["problem"] for r in report["held"] if r["where"].endswith('"Call Centre Agent (part-time)"')))

    def test_a_bullet_with_no_matching_sentence_of_his_own_is_held_not_kept(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        bullets(resume, "Shift Lead").append("Configured the ticketing software and the Salesforce dashboard for renewals")
        out, report = audit(resume)
        self.assertNotIn("Configured the ticketing software and the Salesforce dashboard for renewals", bullets(out, "Shift Lead"))
        self.assertTrue(any("ticketing software" in h["text"] for h in report["held"]))

    def test_faithful_bullets_and_paraphrases_are_left_alone(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["experience"][0]["bullets"] = ["Opened and closed the store and kept the daily cash count accurate", "Counted inventory every week",
                                              "Trained new hires on the POS system and store procedures", "Scheduled 6 associates each week"]
        out, report = audit(resume)
        self.assertEqual(bullets(out, "Shift Lead"), resume["experience"][0]["bullets"])
        about_shift_lead = [r for r in report["restored"] + report["held"] if r["where"].endswith('"Shift Lead"')]
        self.assertEqual(about_shift_lead, [])  # the other two roles still carry the writer's embellished bullets
        self.assertTrue(all(n["where"].endswith('"Shift Lead"') for n in report["notes"] if "every" in n["text"]))  # a paraphrase is at most a note

    def test_a_duplicate_of_a_line_already_there_is_dropped_not_repeated(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        bullets(resume, "Shift Lead").append("Counted inventory weekly, tracking calendar changes")
        out, report = audit(resume)
        self.assertEqual(bullets(out, "Shift Lead").count("Counted inventory weekly"), 1)
        self.assertTrue(any(r["after"] == "" for r in report["restored"]))

    def test_a_role_that_cannot_be_matched_is_left_as_written(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["experience"][0]["title"] = "Store Director"
        out, _ = audit(resume)
        self.assertEqual(bullets(out, "Store Director"), bullets(WRITER_OUTPUT, "Shift Lead"))

    def test_a_confirmed_fact_counts_as_evidence(self):
        out, _ = audit(facts="- Coordinated shift coverage and calendars for the team")
        self.assertIn("Scheduled 6 associates each week, coordinating shift coverage and calendars", bullets(out, "Shift Lead"))

    def test_the_input_is_not_modified(self):
        before = copy.deepcopy(WRITER_OUTPUT)
        provenance.audit_and_repair(WRITER_OUTPUT, PROFILE, POSTING, "", "Customer Success Associate", PLAN)
        self.assertEqual(WRITER_OUTPUT, before)


class C_SummaryAndSkills(unittest.TestCase):
    def test_a_positioning_sentence_under_the_postings_role_name_is_left_out_and_the_rest_stays(self):
        out, report = audit()
        self.assertEqual(out["summary"], "Customer-facing professional with experience across retail sales, shift leadership, and phone-based order support.")
        self.assertEqual(report["held"][0]["problem"], "places you in the posting's role name")

    def test_positioning_that_his_history_does_state_is_kept(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["summary"] = "Well suited to customer service work."
        out, report = audit(resume)
        self.assertEqual(out["summary"], "Well suited to customer service work.")
        self.assertEqual(report["held"], [])

    def test_a_sentence_stating_an_unevidenced_requirement_is_left_out(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["summary"] = "Experienced with ticketing software and customer service."
        out, report = audit(resume)
        self.assertEqual(out["summary"], "")
        self.assertIn("ticketing software", report["held"][0]["problem"])

    def test_customer_success_cannot_be_printed_as_a_skill_but_backed_terms_stay(self):
        out, report = audit()
        self.assertEqual(report["skills_removed"], ["Customer Success"])
        self.assertEqual(out["skills"][0], "Customer Service: Customer Service, Customer Service Certificate, De-escalation")
        self.assertEqual(out["skills"][1], "Operations & Tools: POS Systems, Scheduling, Phone Communication")

    def test_a_none_term_is_removed_even_when_its_words_are_in_the_history(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["skills"].append("Tools: Salesforce")
        out, report = audit(resume)
        self.assertIn("Salesforce", report["skills_removed"])

    def test_without_a_plan_only_the_posting_wording_check_applies(self):
        out, report = audit(terms=None)
        self.assertIn("Customer Success", report["skills_removed"])
        self.assertEqual(len(report["restored"]), 4)


class D_TheNotice(unittest.TestCase):
    def test_a_plain_message_and_one_item_per_change(self):
        _, report = audit()
        notice = provenance.notice_text(report)
        self.assertEqual(notice["count"], 4 + 1 + 1)  # four bullets put back, one summary sentence, one skill
        self.assertIn("put them back to your wording or left them out", notice["message"])
        self.assertIn("add it to that role in your profile and rebuild", notice["message"])
        self.assertEqual(len(notice["items"]), 6)
        self.assertTrue(all(i["text"] and i["change"] and i["why"] for i in notice["items"]))

    def test_nothing_changed_means_no_message(self):
        clean = {**WRITER_OUTPUT, "summary": "", "skills": ["Tools: POS Systems"]}
        clean["experience"] = [{**j, "bullets": [b for b in PROFILE_BULLETS[j["title"]]]} for j in WRITER_OUTPUT["experience"]]
        _, report = audit(clean)
        self.assertEqual(provenance.notice_text(report), {"count": 0, "message": "", "items": []})


PROFILE_BULLETS = {
    "Shift Lead": ["Opened and closed the store and kept the daily cash count accurate", "Scheduled 6 associates each week", "Handled returns and customer complaints, about 20 a week",
                   "Trained new hires on the POS system and store procedures", "Counted inventory weekly"],
    "Sales Associate": ["Helped customers choose products and explained features", "Processed purchases and returns on the POS system", "Resolved upset customers calmly using de-escalation"],
    "Call Centre Agent (part-time)": ["Took inbound customer orders by phone for 4 months", "Confirmed order details and answered delivery questions"],
}


class E_ThroughTheBuild(unittest.TestCase):
    def build(self, terms=PLAN):
        def fake(name, system, user, tool, extract=None):
            if name == "career_term_plan":
                return {"terms": copy.deepcopy(terms)}
            if name == "career_job_build_resume":
                return {"resume_data": copy.deepcopy(WRITER_OUTPUT)}
            raise job_match.JobMatchError("edit unavailable")

        with mock.patch.object(job_match, "_call_with_retry", fake):
            return term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Marcus Bell", "Naperville, IL | marcus.bell@example.com")

    def test_the_finished_resume_has_his_own_sentences_and_no_borrowed_or_posting_wording(self):
        result = self.build()
        text = " ".join(result["resume_data"]["summary"].split() + [b for j in result["resume_data"]["experience"] for b in j["bullets"]] + result["resume_data"]["skills"]).lower()
        for phrase in ("coordinating shift coverage", "calendars", "building rapport", "answering customer questions and handling complaints", "customer success"):
            self.assertNotIn(phrase, text, phrase)
        self.assertEqual(bullets(result["resume_data"], "Shift Lead")[1], "Scheduled 6 associates each week")

    def test_the_notice_reports_it_and_the_report_follows_the_final_resume(self):
        result = self.build()
        self.assertEqual(result["truth_notice"]["provenance"]["count"], 6)
        status = {r["term"]: r["status"] for r in result["term_report"]}
        self.assertNotEqual(status["customer success"], "on_resume")  # no longer on the resume, so no longer reported as on it

    def test_a_clean_build_reports_nothing(self):
        clean = {**WRITER_OUTPUT, "summary": "Customer-facing professional with retail and phone experience.", "skills": ["Tools: POS Systems"]}
        clean["experience"] = [{**j, "bullets": list(PROFILE_BULLETS[j["title"]])} for j in WRITER_OUTPUT["experience"]]
        with mock.patch.object(job_match, "_call_with_retry", lambda name, *a, **k: {"terms": copy.deepcopy(PLAN)} if name == "career_term_plan" else {"resume_data": copy.deepcopy(clean)}):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Marcus Bell", "Naperville, IL | m@example.com")
        self.assertEqual(result["truth_notice"]["provenance"]["count"], 0)
        self.assertEqual(result["resume_data"]["experience"][0]["bullets"], PROFILE_BULLETS["Shift Lead"])


class F_SavedWithTheResume(OwnershipTestCase):
    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.dict(os.environ, {"RATE_LIMIT_USER": "1000/60"}), mock.patch.object(abuse_guard, "LIMITER", abuse_guard.SlidingWindowLimiter())):
            patcher.start()
            self.addCleanup(patcher.stop)
        abuse_guard.IN_FLIGHT.reset()
        self.onboard(self.a)

    def test_the_provenance_report_is_saved_in_the_truth_review_only_when_it_changed_something(self):
        report = {"restored": [{"where": "w", "before": "b", "after": "a", "basis": "x"}], "held": [], "skills_removed": [], "notes": [], "count": 1, "message": "m", "items": []}

        def fake_build(profile_text, job_description, confirmed_facts, name, contact, denials, answers_text="", saved_terms=None):
            return {"resume_data": copy.deepcopy(WRITER_OUTPUT), "role_selection": [], "term_report": [], "ats_match": None, "provenance": report}

        with mock.patch("career.routes.build_checked_resume", fake_build):
            res = self.call("POST", "/job-build-resume", self.a, json={"job_description": POSTING, "name": "Marcus Bell", "contact": "Naperville, IL | m@example.com",
                                                                        "confirmed_facts": [], "qa_history": []})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["resume_data"]["truth_review"]["provenance"]["count"], 1)
        with self.Session() as s:
            self.assertEqual(s.query(ResumeVersion).count(), 1)


if __name__ == "__main__":
    unittest.main()
