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


class G_NewFactualAssertionsAreNeverKeptAsWritten(unittest.TestCase):
    """Review concern 1: an invented bullet that overlaps neither another role nor the posting used to be kept and only noted."""
    INVENTED = ["Organized quarterly safety audits for the Naperville store", "Maintained the store's inventory database",
                "Negotiated supplier discounts with regional vendors"]

    def shift_lead(self, bullet):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["experience"][0]["bullets"] = [bullet]
        return audit(resume)

    def test_invented_bullets_with_no_overlap_are_held_out(self):
        for bullet in self.INVENTED:
            out, report = self.shift_lead(bullet)
            self.assertEqual(bullets(out, "Shift Lead"), [], bullet)
            self.assertEqual([h["text"] for h in report["held"] if h["where"].endswith('"Shift Lead"')], [bullet])
            self.assertIn("adds new facts your Shift Lead entry does not state", report["held"][0]["problem"])

    def test_a_harmless_paraphrase_is_kept_and_listed_as_not_verified(self):
        out, report = self.shift_lead("Assisted new hires with the POS system and store procedures")
        self.assertEqual(bullets(out, "Shift Lead"), ["Assisted new hires with the POS system and store procedures"])
        self.assertEqual(report["notes"][0]["words"], ["Assisted"])
        notice = provenance.notice_text(report)
        self.assertTrue(any(i["change"] == "kept, not verified" and "Assisted" in i["why"] for i in notice["items"]))
        self.assertIn("not verified", notice["message"])

    def test_a_reordering_with_no_new_words_is_kept_without_a_note(self):
        out, report = self.shift_lead("Kept the daily cash count accurate when opening and closing the store")
        self.assertEqual(len(bullets(out, "Shift Lead")), 1)
        self.assertEqual(report["notes"], [])

    def test_a_bullet_that_merges_several_of_his_sentences_is_put_back_to_all_of_them(self):
        merged = "Scheduled 6 associates each week, trained new hires on the POS system and kept the daily cash count accurate, coordinating calendars"
        out, report = self.shift_lead(merged)
        self.assertEqual(bullets(out, "Shift Lead"), ["Opened and closed the store and kept the daily cash count accurate", "Scheduled 6 associates each week",
                                                    "Trained new hires on the POS system and store procedures"])
        self.assertEqual(len([r for r in report["restored"] if r["where"].endswith('"Shift Lead"')]), 1)  # nothing true was lost: every sentence it drew on is back, in his words

    def test_every_notice_item_says_what_happened_and_never_calls_anything_verified(self):
        _, report = audit()
        notice = provenance.notice_text(report)
        self.assertNotIn("verified:", notice["message"])
        for item in notice["items"]:
            head = item["change"].split(":")[0].split(" (")[0]
            self.assertTrue(head in ("now reads", "left out", "kept, not checked", "kept, not verified") or head.startswith("left out of your "), head)


class H_UnmatchedRolesAreNamedNotDeleted(unittest.TestCase):
    """Review concern 2."""
    def with_unmatched(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["experience"].append({"title": "Store Director", "subtitle": "Hearthside Home Goods Co. — 2022 – Present", "bullets": ["Led a team of 40 across three stores"]})
        return audit(resume)

    def test_the_role_and_its_bullets_are_kept_and_named_as_unverified(self):
        out, report = self.with_unmatched()
        self.assertEqual(bullets(out, "Store Director"), ["Led a team of 40 across three stores"])  # nothing true is deleted
        self.assertEqual([(r["title"], r["nearest"]) for r in report["unverified_roles"]], [("Store Director", "Shift Lead at Hearthside Home Goods")])

    def test_the_notice_says_it_was_not_checked_and_offers_the_nearest_saved_role(self):
        _, report = self.with_unmatched()
        notice = provenance.notice_text(report)
        item = next(i for i in notice["items"] if i["change"] == "kept, not checked")
        self.assertIn("Store Director", item["text"])
        self.assertIn("did you mean Shift Lead at Hearthside Home Goods?", item["why"])
        self.assertIn("1 role could not be matched to your saved profile", notice["message"])
        self.assertIn("kept but not checked", notice["message"])

    def test_matched_roles_are_not_reported(self):
        _, report = audit()
        self.assertEqual(report["unverified_roles"], [])

    def test_the_unverified_role_survives_the_build_and_is_in_the_saved_report(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["experience"].append({"title": "Store Director", "subtitle": "Elsewhere Inc — 2022", "bullets": ["Ran the store"]})
        with mock.patch.object(job_match, "_call_with_retry", lambda name, *a, **k: {"terms": copy.deepcopy(PLAN)} if name == "career_term_plan" else {"resume_data": copy.deepcopy(resume)}):
            result = term_pipeline.build_checked_resume(PROFILE, POSTING, [], "Marcus Bell", "Naperville, IL | m@example.com")
        self.assertEqual([r["title"] for r in result["provenance"]["unverified_roles"]], ["Store Director"])
        self.assertIn("Ran the store", result["resume_data"]["experience"][-1]["bullets"])


class I_TransferableSkillsOnlyWhenTheirWordsAppearTogether(unittest.TestCase):
    """PR-2c: "Scheduling Calls" (scheduling staff plus a call-centre job) must not print as a skill. The recombination rule leaves other transferable
    labels alone; the posting-wording rule can still remove one the posting names (see class J)."""
    def plan(self, *extra):
        return PLAN + list(extra)

    def test_a_recombination_of_words_that_never_appear_together_is_removed(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["skills"] = ["Operations & Tools: POS Systems, Scheduling, Scheduling Calls"]
        out, report = audit(resume, terms=self.plan({"term": "scheduling calls", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "x"}))
        self.assertEqual(out["skills"], ["Operations & Tools: POS Systems, Scheduling"])
        self.assertEqual(report["skills_removed"], ["Scheduling Calls"])
        self.assertIn("never appear together", report["skills_detail"][0]["why"])

    def test_a_transferable_label_whose_words_do_appear_together_stays(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["skills"] = ["Team: New Hire Training"]
        out, report = audit(resume, terms=self.plan({"term": "new hire training", "kind": "skill", "importance": "mentioned", "support": "transferable", "evidence": "x"}))
        self.assertEqual(out["skills"], ["Team: New Hire Training"])
        self.assertEqual(report["skills_removed"], [])

    def test_the_recombination_rule_alone_leaves_a_label_with_a_word_the_history_never_uses_in_place(self):
        # Only the recombination rule is under test here, so the posting does NOT name the label ("service" is absent from it). When the posting
        # does name it and no confirmed fact supports it, the posting-wording rule removes it: class J.
        profile ="EXPERIENCE:\n- Cashier at Sears (2019 – 2024)\n  * Processed customer purchases.\n  * Handled cash payments.\n  * Assisted customers.\n"
        resume = {"summary": "", "skills": ["Customer Service: Customer Service, Cash Handling"], "education": [], "certifications": [],
                  "experience": [{"title": "Cashier", "subtitle": "Sears — 2019 – 2024", "bullets": ["Assisted customers."]}]}
        terms = [{"term": "customer service", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "assisted customers"},
                 {"term": "cash handling", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "handled cash payments"}]
        out, report = provenance.audit_and_repair(resume, profile, "Bank Teller. Help customers and handle cash accurately.", "", "Bank Teller", terms)
        self.assertEqual(out["skills"], ["Customer Service: Customer Service, Cash Handling"])
        self.assertEqual(report["skills_removed"], [])

    def test_a_skill_the_plan_backs_is_never_removed_by_this_rule(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["skills"] = ["Operations & Tools: Scheduling Calls"]
        out, _ = audit(resume, terms=self.plan({"term": "scheduling calls", "kind": "skill", "importance": "required", "support": "related", "evidence": "Scheduled 6 associates each week"}))
        self.assertEqual(out["skills"], ["Operations & Tools: Scheduling Calls"])

    def test_a_skill_that_only_contains_a_backed_term_is_still_checked_on_its_own(self):
        # "scheduling" is backed (literal) in PLAN's history; "Scheduling Calls" adds a word and must not ride on it
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["skills"] = ["Operations & Tools: Scheduling, Scheduling Calls"]
        terms = self.plan({"term": "scheduling", "kind": "skill", "importance": "mentioned", "support": "literal", "evidence": "Skills list"},
                          {"term": "scheduling calls", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "x"})
        out, report = audit(resume, terms=terms)
        self.assertEqual(out["skills"], ["Operations & Tools: Scheduling"])
        self.assertEqual(report["skills_removed"], ["Scheduling Calls"])


class J_SearsCashierCustomerService(unittest.TestCase):
    """The Sears cashier example (review of PR #61). The history says the candidate "assisted customers"; the posting asks for "Customer Service";
    no confirmed fact says they did customer service. The label must not appear in Skills on that alone, and the real experience must stay
    represented as transferable experience, never lost and never promoted to a verified skill."""
    PROFILE = "EXPERIENCE:\n- Cashier at Sears (2019 – 2024)\n  * Processed customer purchases.\n  * Handled cash payments.\n  * Assisted customers.\n  * Resolved basic customer concerns.\n"
    POSTING = "Bank Teller. Process deposits and payments accurately; handle cash; provide friendly customer service; resolve customer concerns."
    TERMS = [{"term": "customer service", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "Cashier at Sears: assisted customers and resolved basic customer concerns"},
             {"term": "cash handling", "kind": "skill", "importance": "required", "support": "transferable", "evidence": "Cashier at Sears: handled cash payments"}]
    WRITER = {"name": "Sam Ortiz", "contact": "Chicago, IL | sam@example.com", "headline": "", "summary": "",
              "skills": ["Customer Service: Customer Service, Cash Handling"], "education": [], "certifications": [],
              "experience": [{"title": "Cashier", "subtitle": "Sears — 2019 – 2024", "bullets": ["Assisted customers.", "Handled cash payments."]}]}

    def audit(self, facts=""):
        return provenance.audit_and_repair(copy.deepcopy(self.WRITER), self.PROFILE, self.POSTING, facts, "Bank Teller", copy.deepcopy(self.TERMS))

    def test_customer_service_is_not_printed_as_a_skill_on_assisted_customers_alone(self):
        out, report = self.audit()
        self.assertEqual(report["skills_removed"], ["Customer Service"])
        self.assertEqual(out["skills"], ["Cash Handling"])  # the group label is left out too; the supported skill under it stays
        self.assertEqual(report["skills_detail"], [{"skill": "Customer Service", "why": "uses the posting's wording, which your history does not say"}])
        self.assertEqual(report["labels"], [{"where": "skills group label", "text": "Customer Service", "why": "uses the posting's wording, which your history does not say"}])

    def test_the_legitimate_customer_facing_experience_stays_as_his_own_bullet(self):
        out, report = self.audit()
        self.assertEqual(bullets(out, "Cashier"), ["Assisted customers.", "Handled cash payments."])
        self.assertEqual(report["restored"] + report["held"], [])  # nothing about the experience itself was changed

    def test_the_removal_is_reported_to_the_candidate_never_silent(self):
        _, report = self.audit()
        items = [i for i in provenance.notice_text(report)["items"] if i["text"] == "Customer Service"]
        self.assertEqual(len(items), 1)  # left out of the group label AND the skills: one item, not two
        self.assertEqual((items[0]["change"], items[0]["why"]), ("left out of your skills group label and skills", "uses the posting's wording, which your history does not say"))

    def test_a_confirmed_fact_that_states_it_puts_the_skill_back(self):
        out, report = self.audit(facts="- Provided customer service at the register")
        self.assertEqual(out["skills"], ["Customer Service: Customer Service, Cash Handling"])
        self.assertEqual(report["skills_removed"], [])

    def test_through_the_build_it_is_off_the_skills_line_and_kept_as_transferable_experience(self):
        def fake(name, system, user, tool, extract=None):
            if name == "career_term_plan":
                return {"terms": copy.deepcopy(self.TERMS)}
            if name == "career_job_build_resume":
                return {"resume_data": copy.deepcopy(self.WRITER)}
            raise job_match.JobMatchError("edit unavailable")

        with mock.patch.object(job_match, "_call_with_retry", fake):
            result = term_pipeline.build_checked_resume(self.PROFILE, self.POSTING, [], "Sam Ortiz", "Chicago, IL | sam@example.com")
        resume = result["resume_data"]
        skill_items = [i.strip().lower() for line in resume["skills"] for i in (line.partition(":")[2] if ":" in line else line).split(",")]
        self.assertFalse(any(line.lower().startswith("customer service") for line in resume["skills"]), "no 'Customer Service' group label either")
        self.assertNotIn("customer service", skill_items)  # not in the verified Skills section
        self.assertIn("cash handling", skill_items)
        self.assertIn("Assisted customers.", bullets(resume, "Cashier"))  # the experience itself is still on the resume
        entry = next(t for t in result["term_report"] if t["term"] == "customer service")
        self.assertEqual(entry["support"], "transferable")  # still reported as transferable experience, with its evidence, never as verified
        self.assertIn("assisted customers", entry["evidence"])
        self.assertIn("Customer Service", result["truth_notice"]["provenance"]["skills_removed"])


class K_HeadlineAndSkillsLabels(unittest.TestCase):
    """Fix A (headline) and Fix B (skills group labels): the existing Skills-item evidence decision, applied to every headline phrase and every group
    label. Eight scenarios from the approved plan, with the Sears cashier and the Marcus live-run fixtures. Summary filtering is NOT broadened (Fix C is
    deferred): the summary is deliberately outside the same-standard test below."""
    S = J_SearsCashierCustomerService

    def sears(self, headline="Customer Service | Cash Handling | Transaction Accuracy", skills=None, bullets_=None, facts=""):
        resume = copy.deepcopy(self.S.WRITER)
        resume["headline"] = headline
        resume["skills"] = skills if skills is not None else ["Customer Service: Customer Service, Cash Handling"]
        if bullets_ is not None:
            resume["experience"][0]["bullets"] = bullets_
        return provenance.audit_and_repair(resume, self.S.PROFILE, self.S.POSTING, facts, "Bank Teller", copy.deepcopy(self.S.TERMS))

    # 1. Sears, no confirmed fact
    def test_1_sears_headline_and_label_do_not_present_customer_service_without_a_confirmed_fact(self):
        out, report = self.sears()
        self.assertEqual(out["headline"], "Cash Handling")  # "Customer Service" and "Transaction Accuracy" use the posting's wording, which the history does not say
        self.assertEqual(out["skills"], ["Cash Handling"])
        self.assertEqual(bullets(out, "Cashier"), ["Assisted customers.", "Handled cash payments."])  # his own words stay
        self.assertEqual({(l["where"], l["text"]) for l in report["labels"]},
                         {("headline", "Customer Service"), ("headline", "Transaction Accuracy"), ("skills group label", "Customer Service")})

    # 2. Confirmed fact keeps the label eligible
    def test_2_a_confirmed_fact_keeps_the_headline_phrase_and_the_label(self):
        out, report = self.sears(facts="- Provided customer service at the register")
        self.assertIn("Customer Service", out["headline"].split(" | "))
        self.assertEqual(out["skills"], ["Customer Service: Customer Service, Cash Handling"])
        self.assertNotIn("Customer Service", [l["text"] for l in report["labels"]])

    # 3. Marcus live fixture: his headline and labels are untouched
    def test_3_marcus_headline_and_labels_are_unchanged(self):
        out, report = audit()
        self.assertEqual(out["headline"], WRITER_OUTPUT["headline"])
        self.assertEqual([l for l in report["labels"] if l["where"] == "headline"], [])
        self.assertEqual([line.partition(":")[0] for line in out["skills"]], [line.partition(":")[0] for line in WRITER_OUTPUT["skills"]])
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["headline"] = "Customer Service Professional | De-Escalation & Complaint Resolution | Retail Team Leadership"
        out2, report2 = audit(resume)
        self.assertEqual(out2["headline"], resume["headline"])  # his real headline from the live run passes phrase by phrase
        self.assertEqual(report2["labels"], [])

    # 4. Role-name, none-term and backed phrases
    def test_4_role_name_and_no_evidence_phrases_are_left_out_and_a_backed_phrase_stays(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["headline"] = "Customer Success Specialist | Salesforce Administrator | De-Escalation"
        out, report = audit(resume)
        self.assertEqual(out["headline"], "De-Escalation")
        why = {l["text"]: l["why"] for l in report["labels"]}
        self.assertEqual(why["Salesforce Administrator"], "a requirement your history does not establish")
        self.assertIn("posting's wording", why["Customer Success Specialist"])

    # 5. Empty headline, on screen and in the Word file
    def test_5_an_empty_headline_is_accepted_and_the_word_file_builds(self):
        resume = copy.deepcopy(WRITER_OUTPUT)
        resume["headline"] = "Customer Success Specialist | Salesforce Administrator"
        out, _ = audit(resume)
        self.assertEqual(out["headline"], "")
        text = self.docx_text(out)
        self.assertNotIn("Salesforce", text)
        self.assertIn("Shift Lead", text)

    @staticmethod
    def docx_text(resume):
        import io
        from docx import Document
        import resume_builder as rb
        doc = Document(io.BytesIO(rb.build_resume_bytes({**resume, "skills_style": "grouped"}, ats_mode=False, template="classic")))
        return "\n".join(p.text for p in doc.paragraphs)

    # 6. The same label is handled the same way everywhere except the summary (deferred)
    def test_6_the_same_unsupported_label_is_absent_from_headline_skills_label_skills_and_bullets(self):
        out, report = self.sears(headline="Customer Service | Cash Handling", skills=["Customer Service: Customer Service, Cash Handling"],
                                 bullets_=["Assisted customers.", "Provided friendly customer service"])
        everywhere = " | ".join([out["headline"]] + out["skills"] + bullets(out, "Cashier")).lower()
        self.assertNotIn("customer service", everywhere)
        self.assertIn("cash handling", everywhere)
        self.assertIn("assisted customers.", everywhere)  # his own words stay

    # 7. Removing a label never removes the supported skills under it, and a partly supported label keeps its supported part
    def test_7_a_removed_label_keeps_the_supported_skills_under_it_and_a_partly_supported_label_keeps_its_part(self):
        out, _ = self.sears(skills=["Customer Service: Cash Handling, Transaction Processing"])
        self.assertEqual(out["skills"], ["Cash Handling, Transaction Processing"])
        out2, report2 = self.sears(headline="Cash Handling", skills=["Customer Service & Cash Handling: Cash Handling, Transaction Processing"])
        self.assertEqual(out2["skills"], ["Cash Handling: Cash Handling, Transaction Processing"])
        self.assertEqual([l["text"] for l in report2["labels"]], ["Customer Service"])

    # 8. Deduplicated notice
    def test_8_a_label_left_out_in_several_places_is_one_notice_item_and_one_count(self):
        _, report = self.sears(headline="Customer Service | Cash Handling")
        notice = provenance.notice_text(report)
        items = [i for i in notice["items"] if i["text"] == "Customer Service"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["change"], "left out of your headline, skills group label and skills")
        self.assertEqual(notice["count"], 1)
        self.assertIn("1 statement was not in your own words", notice["message"])

    # Output locations: on-screen content and the Word file both carry the correction
    def test_the_on_screen_resume_and_the_word_file_both_reflect_the_corrected_headline_and_skills(self):
        def fake(name, system, user, tool, extract=None):
            if name == "career_term_plan":
                return {"terms": copy.deepcopy(self.S.TERMS)}
            if name == "career_job_build_resume":
                return {"resume_data": {**copy.deepcopy(self.S.WRITER), "headline": "Customer Service | Cash Handling | Transaction Accuracy"}}
            raise job_match.JobMatchError("edit unavailable")

        with mock.patch.object(job_match, "_call_with_retry", fake):
            result = term_pipeline.build_checked_resume(self.S.PROFILE, self.S.POSTING, [], "Sam Ortiz", "Chicago, IL | sam@example.com")
        resume = result["resume_data"]
        self.assertEqual(resume["headline"], "Cash Handling")  # what the page and the saved version carry
        self.assertEqual(resume["skills"], ["Cash Handling"])
        text = self.docx_text(resume)  # what the Word file prints
        self.assertNotIn("customer service", text.lower())
        self.assertIn("Cash Handling", text)
        self.assertIn("Assisted customers.", text)
        entry = next(t for t in result["term_report"] if t["term"] == "customer service")
        self.assertEqual((entry["support"], entry["status"]), ("transferable", "transferable"))  # still reported as relevant experience, never as on the resume
        notice = result["truth_notice"]["provenance"]
        self.assertEqual([i["change"] for i in notice["items"] if i["text"] == "Customer Service"], ["left out of your headline, skills group label and skills"])


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
