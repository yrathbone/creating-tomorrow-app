"""Unit tests for the general-profile truthfulness checker (career/resume_quality.py general_truth_findings).

C-52 Step A, revised 2026-11-14 after Data's independent review. Deterministic checks only: no route, AI, database or paid call.
The checker is not wired into generation, download or approval, and these tests do not change that.

Classifications: SUPPORTED, DERIVED, UNSUPPORTED, UNCERTAIN. Fixtures are the synthetic Accounts A and B.
Word lists and token matching are deterministic signals, not guarantees of semantic truth (see the limitations in the report).

Run from the backend folder:  py -3.12 -m unittest tests.test_general_truth_checker -v
"""
import copy
import unittest

from career.resume_quality import DERIVED, SUPPORTED, UNCERTAIN, UNSUPPORTED, general_truth_findings

# Saved data for synthetic Account B. Months are stored as the app stores them (06/21 and 05/25 on the review screen).
B_FACTS = {
    "roles": [{
        "id": 1, "title": "Coordinator", "organization": "Fictional Organization Beta", "years": [2021, 2025],
        "start": (2021, 6), "end": (2025, 5),
        "text": "Handled customer requests and kept records for a fictional office of eight. Improved the record-keeping checklist.",
    }],
    "education": [{"school": "Fictional School B", "degree": "Certificate", "text": "Customer Service"}],
    "skills": ["Customer support", "Record keeping", "Calendar planning", "Written communication"],
}
B_RESUME = {
    "headline": "Customer Support Coordinator | Records & Office Operations",
    "summary": (
        "Service-oriented coordinator with experience handling customer requests and maintaining records for a small office team. "
        "Skilled in record keeping, calendar planning, and written communication, with a track record of improving administrative processes. "
        "Certified in customer service and dependable in fast-paced, detail-driven environments."
    ),
    "skills": ["Customer Support", "Record Keeping", "Calendar Planning", "Written Communication", "Process Improvement", "Office Administration"],
    "experience": [{
        "title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
        "bullets": ["Handled customer requests and maintained records for a fictional office of eight.",
                    "Improved the record-keeping checklist, streamlining documentation practices."],
    }],
    "education": ["Fictional School B: Certificate, Customer Service"],
}

# Saved data for synthetic Account A.
A_FACTS = {
    "roles": [{
        "id": 1, "title": "Operations Coordinator", "organization": "Fictional Organization Alpha", "years": [2021, 2023],
        "start": (2021, 1), "end": (2023, 3),
        "text": "Coordinated scheduling and reporting for a fictional team of six. Maintained a shared tracker and reduced weekly report preparation time.",
    }],
    "education": [{"school": "Fictional School", "degree": "Certificate in Office Administration", "text": ""}],
    "skills": ["Scheduling", "Reporting", "Spreadsheet tracking", "Written communication", "Teamwork"],
}
A_RESUME = {
    "headline": "Operations Coordination | Scheduling & Reporting | Team Support",
    "summary": (
        "Operations professional with experience coordinating scheduling and reporting for a team, maintaining shared trackers, and improving "
        "report turnaround time. Known for dependable written communication and effective teamwork in fast-paced coordination roles. "
        "Holds a Certificate in Office Administration."
    ),
    "skills": ["Scheduling", "Reporting", "Spreadsheet Tracking", "Written Communication", "Teamwork", "Operations Coordination"],
    "experience": [{
        "title": "Operations Coordinator", "subtitle": "Fictional Organization Alpha — Jan 2021 – Mar 2023",
        "bullets": ["Coordinated scheduling and reporting for a team of six.", "Maintained a shared tracker to support team coordination.",
                    "Reduced weekly report preparation time through improved tracking processes."],
    }],
    "education": ["Fictional School: Certificate in Office Administration"],
}


def _find(findings, where=None, text_contains=None):
    return [f for f in findings
            if (where is None or f["where"] == where) and (text_contains is None or text_contains.lower() in f["text"].lower())]


def _classes(findings, where=None, text_contains=None):
    return [f["classification"] for f in _find(findings, where, text_contains)]


def _resume(**overrides):
    base = {"headline": "", "summary": "", "skills": [], "experience": [], "education": []}
    base.update(overrides)
    return base


class ResultShapeAndImmutability(unittest.TestCase):
    def test_every_finding_has_the_structured_fields_and_a_known_class(self):
        for res, facts in ((B_RESUME, B_FACTS), (A_RESUME, A_FACTS)):
            for f in general_truth_findings(res, facts):
                self.assertEqual(set(f), {"where", "text", "classification", "source", "explanation"})
                self.assertIn(f["classification"], {SUPPORTED, DERIVED, UNSUPPORTED, UNCERTAIN})
                self.assertTrue(f["explanation"])

    def test_empty_inputs_return_no_findings(self):
        self.assertEqual(general_truth_findings({}, {}), [])
        self.assertEqual(general_truth_findings(None, None), [])

    def test_the_inputs_are_never_modified(self):
        res, facts = copy.deepcopy(B_RESUME), copy.deepcopy(B_FACTS)
        general_truth_findings(res, facts)
        self.assertEqual(res, B_RESUME)
        self.assertEqual(facts, B_FACTS)


class AccountBUnsupportedContent(unittest.TestCase):
    def setUp(self):
        self.findings = general_truth_findings(B_RESUME, B_FACTS)

    def test_office_administration_skill_is_unsupported(self):
        self.assertEqual(_classes(self.findings, where="skills[5]", text_contains="Office Administration"), [UNSUPPORTED])

    def test_customer_support_coordinator_headline_is_an_unsupported_title_claim(self):
        self.assertEqual(_classes(self.findings, where="headline[0]"), [UNSUPPORTED])

    def test_office_operations_in_the_headline_is_uncertain(self):
        self.assertEqual(_classes(self.findings, where="headline[1]"), [UNCERTAIN])

    def test_certified_for_a_certificate_is_an_unsupported_credential(self):
        hits = [f for f in self.findings if f["where"] == "summary[2]" and "certified" in f["explanation"].lower()]
        self.assertEqual([f["classification"] for f in hits], [UNSUPPORTED])

    def test_track_record_and_administrative_scope_are_unsupported(self):
        self.assertTrue(_classes(self.findings, where="summary[1]", text_contains="track record"))
        self.assertTrue(all(c == UNSUPPORTED for c in _classes(self.findings, where="summary[1]")))

    def test_unsourced_soft_claims_are_unsupported(self):
        for word in ("dependable", "fast paced"):
            with self.subTest(word=word):
                hits = [f for f in self.findings if f["where"] == "summary[2]" and word in f["explanation"]]
                self.assertEqual({f["classification"] for f in hits}, {UNSUPPORTED})

    def test_b_summary_is_never_reported_as_fully_supported(self):
        self.assertFalse(_find(self.findings, where="summary[2]", text_contains="") and
                         all(f["classification"] == SUPPORTED for f in _find(self.findings, where="summary[2]")))


class AccountAChecks(unittest.TestCase):
    def setUp(self):
        self.findings = general_truth_findings(A_RESUME, A_FACTS)

    def test_operations_coordination_is_derived_from_the_held_title_with_a_reference(self):
        hits = _find(self.findings, where="skills[5]")
        self.assertEqual([f["classification"] for f in hits], [DERIVED])
        self.assertIn("role 1", hits[0]["source"])
        self.assertIn("Operations Coordinator", hits[0]["source"])

    def test_known_for_dependable_is_an_unsupported_soft_claim(self):
        hits = [f for f in self.findings if f["where"] == "summary[1]" and "dependable" in f["explanation"]]
        self.assertEqual({f["classification"] for f in hits}, {UNSUPPORTED})

    def test_team_support_is_uncertain_because_support_is_not_in_the_source(self):
        self.assertEqual(_classes(self.findings, where="headline[2]"), [UNCERTAIN])

    def test_certificate_in_office_administration_is_supported_by_saved_education(self):
        self.assertEqual(_classes(self.findings, where="education[0]"), [SUPPORTED])

    def test_a_faithful_entry_is_supported_with_its_role_reference(self):
        hits = _find(self.findings, where="experience[0]")
        self.assertEqual([f["classification"] for f in hits], [SUPPORTED])
        self.assertIn("role 1", hits[0]["source"])


class DateExactness(unittest.TestCase):
    """Data finding 1: years alone must not be treated as month-exact. Months are checked only where the saved data has them."""

    def _entry(self, subtitle, facts=None):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": subtitle, "bullets": []}])
        return _find(general_truth_findings(res, facts or B_FACTS), where="experience[0]")

    def test_exact_saved_months_match_is_supported(self):
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 06/21 – 05/25")], [SUPPORTED])

    def test_a_different_saved_month_is_unsupported(self):
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 01/21 – 05/25")], [UNSUPPORTED])

    def test_a_different_saved_end_month_is_unsupported(self):
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 06/21 – 12/25")], [UNSUPPORTED])

    def test_a_wrong_year_is_unsupported(self):
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 06/19 – 05/25")], [UNSUPPORTED])

    def test_a_month_is_uncertain_when_only_years_are_saved(self):
        years_only = copy.deepcopy(B_FACTS)
        years_only["roles"][0].pop("start")
        years_only["roles"][0].pop("end")
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 01/21 – 12/25", years_only)], [UNCERTAIN])

    def test_a_year_only_entry_matches_year_only_saved_data(self):
        years_only = copy.deepcopy(B_FACTS)
        years_only["roles"][0].pop("start")
        years_only["roles"][0].pop("end")
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 2021 – 2025", years_only)], [SUPPORTED])

    def test_an_ongoing_claim_against_a_saved_end_date_is_unsupported(self):
        self.assertEqual([f["classification"] for f in self._entry("Fictional Organization Beta — 06/21 – present")], [UNSUPPORTED])


class BulletChecks(unittest.TestCase):
    """Data finding 2: bullet-level amounts, scope, credentials and named items, with the entry's own classification kept separate."""

    def _run(self, bullet, facts=None):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25", "bullets": [bullet]}])
        return general_truth_findings(res, facts or B_FACTS)

    def test_a_budget_amount_claim_is_unsupported_even_though_the_entry_is_supported(self):
        findings = self._run("Managed a $10 million budget for the office.")
        self.assertEqual(_classes(findings, where="experience[0]"), [SUPPORTED])          # the entry header
        bullet_hits = _find(findings, where="experience[0].bullets[0]")
        self.assertIn(UNSUPPORTED, [f["classification"] for f in bullet_hits])
        self.assertTrue(any("10 million" in f["explanation"] for f in bullet_hits))
        self.assertTrue(any("budget" in f["explanation"] or "Managed" in f["explanation"] or "managed" in f["explanation"] for f in bullet_hits))

    def test_an_invented_scope_word_is_unsupported(self):
        self.assertIn(UNSUPPORTED, [f["classification"] for f in _find(self._run("Oversaw the reporting calendar for the office."), where="experience[0].bullets[0]")])

    def test_an_invented_credential_in_a_bullet_is_unsupported(self):
        self.assertIn(UNSUPPORTED, [f["classification"] for f in _find(self._run("Certified in records management."), where="experience[0].bullets[0]")])

    def test_a_named_tool_not_in_the_saved_data_is_uncertain_not_declared_false(self):
        hits = [f["classification"] for f in _find(self._run("Used Salesforce to track customer requests."), where="experience[0].bullets[0]")]
        self.assertIn(UNCERTAIN, hits)
        self.assertNotIn(SUPPORTED, hits)

    def test_a_faithful_bullet_is_supported_with_a_precise_source_reference(self):
        hits = _find(self._run("Handled customer requests and kept records for a fictional office of eight."), where="experience[0].bullets[0]")
        self.assertEqual([f["classification"] for f in hits], [SUPPORTED])
        self.assertIn("role 1", hits[0]["source"])
        self.assertIn("customer requests", hits[0]["source"])

    def test_a_paraphrase_with_content_not_in_the_source_is_uncertain_not_silently_passed(self):
        hits = _find(self._run("Maintained documentation for a fictional office of eight."), where="experience[0].bullets[0]")
        self.assertIn(UNCERTAIN, [f["classification"] for f in hits])


class NumberBoundaries(unittest.TestCase):
    """Number words and digits are equivalent; an amount that differs from the saved data is not."""

    def test_six_in_words_matches_6_in_digits(self):
        facts = copy.deepcopy(A_FACTS)
        res = _resume(experience=[{"title": "Operations Coordinator", "subtitle": "Fictional Organization Alpha — Jan 2021 – Mar 2023",
                                   "bullets": ["Coordinated scheduling and reporting for a team of 6."]}])
        findings = general_truth_findings(res, facts)
        self.assertNotIn(UNSUPPORTED, [f["classification"] for f in _find(findings, where="experience[0].bullets[0]")])

    def test_a_different_team_size_is_unsupported(self):
        res = _resume(experience=[{"title": "Operations Coordinator", "subtitle": "Fictional Organization Alpha — Jan 2021 – Mar 2023",
                                   "bullets": ["Coordinated scheduling and reporting for a team of 8."]}])
        findings = general_truth_findings(res, A_FACTS)
        self.assertIn(UNSUPPORTED, [f["classification"] for f in _find(findings, where="experience[0].bullets[0]")])

    def test_a_percentage_is_not_the_same_as_a_plain_number(self):
        res = _resume(experience=[{"title": "Operations Coordinator", "subtitle": "Fictional Organization Alpha — Jan 2021 – Mar 2023",
                                   "bullets": ["Reduced weekly report preparation time by 40%."]}])
        findings = general_truth_findings(res, A_FACTS)
        self.assertIn(UNSUPPORTED, [f["classification"] for f in _find(findings, where="experience[0].bullets[0]")])


class RoleIdentity(unittest.TestCase):
    """Data item 3: the same title at two employers must match by employer, and the same title and employer twice must not guess."""

    FACTS = {
        "roles": [
            {"id": 7, "title": "Coordinator", "organization": "Alpha Works", "years": [2015, 2017], "text": "Scheduled deliveries for the warehouse."},
            {"id": 8, "title": "Coordinator", "organization": "Beta Health", "years": [2019, 2022], "text": "Handled patient intake calls."},
        ],
        "education": [],
        "skills": [],
    }

    def test_the_entry_matches_the_role_at_the_named_employer(self):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Beta Health — 2019 – 2022", "bullets": ["Handled patient intake calls."]}])
        findings = general_truth_findings(res, self.FACTS)
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [SUPPORTED])
        self.assertIn("role 8", _find(findings, where="experience[0]")[0]["source"])
        self.assertIn(SUPPORTED, [f["classification"] for f in _find(findings, where="experience[0].bullets[0]")])

    def test_the_employer_must_match_or_the_entry_is_unsupported(self):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Gamma Corp — 2019 – 2022", "bullets": []}])
        findings = general_truth_findings(res, self.FACTS)
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [UNSUPPORTED])

    def test_a_bullet_from_the_other_employer_is_not_credited_to_this_one(self):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Beta Health — 2019 – 2022", "bullets": ["Scheduled deliveries for the warehouse."]}])
        findings = general_truth_findings(res, self.FACTS)
        self.assertNotIn(SUPPORTED, [f["classification"] for f in _find(findings, where="experience[0].bullets[0]")])

    def test_the_same_title_and_employer_twice_with_no_dates_to_separate_them_is_uncertain(self):
        facts = {"roles": [
            {"id": 1, "title": "Coordinator", "organization": "Acme", "years": [2016, 2018], "text": "Did one thing."},
            {"id": 2, "title": "Coordinator", "organization": "Acme", "years": [2020, 2022], "text": "Did another thing."},
        ], "education": [], "skills": []}
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Acme — 2024", "bullets": []}])
        self.assertEqual([f["classification"] for f in _find(general_truth_findings(res, facts), where="experience[0]")], [UNCERTAIN])


class LegitimateTransferableWording(unittest.TestCase):
    def test_improved_checklist_derives_process_improvement_with_its_source_sentence(self):
        hits = _find(general_truth_findings(B_RESUME, B_FACTS), where="skills[4]")
        self.assertEqual([f["classification"] for f in hits], [DERIVED])
        self.assertIn("checklist", hits[0]["source"])
        self.assertIn("role 1", hits[0]["source"])

    def test_process_improvement_without_a_process_object_is_uncertain(self):
        facts = {"roles": [{"id": 1, "title": "Assistant", "organization": "Org", "years": [2020], "text": "Improved morale in the team."}],
                 "education": [], "skills": []}
        res = _resume(skills=["Process Improvement"])
        self.assertEqual([f["classification"] for f in general_truth_findings(res, facts)], [UNCERTAIN])

    def test_a_skill_the_member_saved_is_supported(self):
        self.assertEqual(_classes(general_truth_findings(B_RESUME, B_FACTS), where="skills[0]"), [SUPPORTED])

    def test_a_descriptive_lowercase_role_word_in_a_sentence_is_not_a_title_claim(self):
        findings = general_truth_findings(B_RESUME, B_FACTS)
        self.assertFalse([f for f in findings if f["where"] == "summary[0]" and f["classification"] == UNSUPPORTED])

    def test_a_descriptive_headline_with_supported_words_is_not_rejected(self):
        findings = general_truth_findings(_resume(headline="Customer-focused professional | Record keeping"), B_FACTS)
        self.assertFalse([f for f in findings if f["classification"] == UNSUPPORTED])

    def test_a_soft_word_the_member_actually_wrote_is_not_flagged(self):
        facts = copy.deepcopy(A_FACTS)
        facts["roles"][0]["text"] += " Known for being dependable on deadlines."
        findings = general_truth_findings(_resume(summary="Known for dependable scheduling."), facts)
        self.assertFalse([f for f in findings if "dependable" in f["explanation"] and f["classification"] == UNSUPPORTED])


class ExactFactualFields(unittest.TestCase):
    def test_an_altered_job_title_is_unsupported(self):
        res = copy.deepcopy(B_RESUME)
        res["experience"][0]["title"] = "Senior Coordinator"
        self.assertEqual(_classes(general_truth_findings(res, B_FACTS), where="experience[0]"), [UNSUPPORTED])

    def test_an_altered_employer_is_unsupported(self):
        res = copy.deepcopy(B_RESUME)
        res["experience"][0]["subtitle"] = "Some Other Company — 06/21 – 05/25"
        self.assertEqual(_classes(general_truth_findings(res, B_FACTS), where="experience[0]"), [UNSUPPORTED])

    def test_a_credential_upgrade_in_education_is_unsupported(self):
        res = copy.deepcopy(B_RESUME)
        res["education"] = ["Fictional School B: Certification, Customer Service"]
        self.assertEqual(_classes(general_truth_findings(res, B_FACTS), where="education[0]"), [UNSUPPORTED])

    def test_an_unknown_school_is_unsupported(self):
        res = copy.deepcopy(B_RESUME)
        res["education"] = ["Imaginary University: Certificate, Customer Service"]
        self.assertEqual(_classes(general_truth_findings(res, B_FACTS), where="education[0]"), [UNSUPPORTED])


class UnsupportedHeadlineTitles(unittest.TestCase):
    """Data item 5: descriptive headline phrases are fine; a title-cased phrase presented as a held job is not."""

    def test_a_held_title_exactly_is_supported(self):
        findings = general_truth_findings(_resume(headline="Coordinator"), B_FACTS)
        self.assertEqual(_classes(findings, where="headline[0]"), [SUPPORTED])  # the held title, matched exactly

    def test_a_senior_title_not_held_is_unsupported(self):
        findings = general_truth_findings(_resume(headline="Senior Coordinator"), B_FACTS)
        self.assertEqual(_classes(findings, where="headline[0]"), [UNSUPPORTED])


class RevisionTwoDatesAndWording(unittest.TestCase):
    """Data's revision-2 findings: absent dates are never fully verified; word overlap alone is never proof of support."""

    def _entry_findings(self, subtitle, facts=None, bullets=None):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": subtitle, "bullets": bullets or []}])
        return general_truth_findings(res, facts or B_FACTS)

    def test_an_entry_with_all_dates_removed_is_uncertain_not_supported(self):
        findings = self._entry_findings("Fictional Organization Beta")
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [UNCERTAIN])

    def test_unreadable_dates_are_uncertain(self):
        findings = self._entry_findings("Fictional Organization Beta — sometime in the early years")
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [UNCERTAIN])

    def test_a_missing_end_date_is_uncertain_when_one_is_saved(self):
        findings = self._entry_findings("Fictional Organization Beta — 06/21")
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [UNCERTAIN])

    def test_a_role_with_no_saved_dates_and_no_entry_dates_is_uncertain(self):
        facts = copy.deepcopy(B_FACTS)
        facts["roles"][0].pop("start")
        facts["roles"][0].pop("end")
        facts["roles"][0]["years"] = []
        findings = self._entry_findings("Fictional Organization Beta", facts)
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [UNCERTAIN])

    def test_year_only_saved_precision_is_preserved_and_not_upgraded_to_months(self):
        facts = copy.deepcopy(B_FACTS)
        facts["roles"][0].pop("start")
        facts["roles"][0].pop("end")
        findings = self._entry_findings("Fictional Organization Beta — 2021 – 2025", facts)
        self.assertEqual([f["classification"] for f in _find(findings, where="experience[0]")], [SUPPORTED])

    def test_a_rearranged_bullet_built_from_saved_words_is_uncertain(self):
        bullet = "Kept customer requests and handled records for a fictional office of eight."
        hits = [f["classification"] for f in _find(self._entry_findings("Fictional Organization Beta — 06/21 – 05/25", bullets=[bullet]),
                                                   where="experience[0].bullets[0]")]
        self.assertEqual(hits, [UNCERTAIN])

    def test_a_substituted_synonym_is_uncertain_not_supported(self):
        bullet = "Handled customer requests and maintained records for a fictional office of eight."
        hits = [f["classification"] for f in _find(self._entry_findings("Fictional Organization Beta — 06/21 – 05/25", bullets=[bullet]),
                                                   where="experience[0].bullets[0]")]
        self.assertEqual(hits, [UNCERTAIN])

    def test_an_exact_saved_sentence_is_supported(self):
        bullet = "Handled customer requests and kept records for a fictional office of eight."
        hits = [f["classification"] for f in _find(self._entry_findings("Fictional Organization Beta — 06/21 – 05/25", bullets=[bullet]),
                                                   where="experience[0].bullets[0]")]
        self.assertEqual(hits, [SUPPORTED])

    def test_a_deletion_only_bullet_in_saved_order_is_supported(self):
        bullet = "Handled customer requests for a fictional office of eight."
        hits = [f["classification"] for f in _find(self._entry_findings("Fictional Organization Beta — 06/21 – 05/25", bullets=[bullet]),
                                                   where="experience[0].bullets[0]")]
        self.assertEqual(hits, [SUPPORTED])

    def test_number_words_and_digits_are_equivalent_for_support(self):
        facts = copy.deepcopy(A_FACTS)
        res = _resume(experience=[{"title": "Operations Coordinator", "subtitle": "Fictional Organization Alpha — Jan 2021 – Mar 2023",
                                   "bullets": ["Coordinated scheduling and reporting for a team of 6."]}])
        hits = [f["classification"] for f in _find(general_truth_findings(res, facts), where="experience[0].bullets[0]")]
        self.assertEqual(hits, [SUPPORTED])

    def test_an_invented_amount_remains_unsupported_after_the_rule_change(self):
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Fictional Organization Beta — 06/21 – 05/25",
                                   "bullets": ["Managed a $10 million budget for the office."]}])
        hits = [f["classification"] for f in _find(general_truth_findings(res, B_FACTS), where="experience[0].bullets[0]")]
        self.assertIn(UNSUPPORTED, hits)
        self.assertNotIn(SUPPORTED, hits)


class RevisionThreeMeaningProtection(unittest.TestCase):
    """Data's revision-3 defect: deletion-only matching must never drop a negation or a meaning-changing qualifier."""

    FACTS = {
        "roles": [{"id": 4, "title": "Analyst", "organization": "Org X", "years": [2019, 2021],
                   "text": "Did not manage the budget. Assisted the manager with reporting. Shared the reporting duties only partly. "
                           "Prepared reports without supervision."}],
        "education": [], "skills": [],
    }

    def _bullet(self, bullet, facts=None):
        res = _resume(experience=[{"title": "Analyst", "subtitle": "Org X — 2019 – 2021", "bullets": [bullet]}])
        return [f["classification"] for f in _find(general_truth_findings(res, facts or self.FACTS), where="experience[0].bullets[0]")]

    # Negative: reversals and meaning changes must not be SUPPORTED.
    def test_dropping_not_from_a_negated_saved_sentence_is_not_supported(self):
        self.assertNotIn(SUPPORTED, self._bullet("Did manage the budget."))

    def test_dropping_the_negation_and_auxiliary_is_not_supported(self):
        self.assertNotIn(SUPPORTED, self._bullet("Manage the budget."))

    def test_dropping_without_is_not_supported(self):
        self.assertNotIn(SUPPORTED, self._bullet("Prepared reports."))

    def test_dropping_the_assistance_qualifier_is_not_supported(self):
        self.assertNotIn(SUPPORTED, self._bullet("Reporting."))

    def test_dropping_the_limit_qualifier_is_not_supported(self):
        self.assertNotIn(SUPPORTED, self._bullet("Shared the reporting duties."))

    def test_adding_a_negation_the_saved_data_does_not_contain_is_not_supported(self):
        facts = {"roles": [{"id": 5, "title": "Analyst", "organization": "Org X", "years": [2019, 2021], "text": "Managed the budget."}],
                 "education": [], "skills": []}
        self.assertNotIn(SUPPORTED, self._bullet("Did not manage the budget.", facts))
        self.assertIn(UNCERTAIN, self._bullet("Did not manage the budget.", facts))

    # Positive: exact matches, harmless shortening and existing derived skills are preserved.
    def test_an_exact_negated_sentence_is_supported(self):
        self.assertEqual(self._bullet("Did not manage the budget."), [SUPPORTED])

    def test_an_exact_assistance_sentence_is_supported(self):
        self.assertEqual(self._bullet("Assisted the manager with reporting."), [SUPPORTED])

    def test_a_harmless_shortening_without_protected_words_is_supported(self):
        facts = {"roles": [{"id": 6, "title": "Coordinator", "organization": "Org Y", "years": [2020, 2021],
                            "text": "Handled customer requests and kept records for a fictional office of eight."}],
                 "education": [], "skills": []}
        res = _resume(experience=[{"title": "Coordinator", "subtitle": "Org Y — 2020 – 2021",
                                   "bullets": ["Handled customer requests for a fictional office of eight."]}])
        hits = [f["classification"] for f in _find(general_truth_findings(res, facts), where="experience[0].bullets[0]")]
        self.assertEqual(hits, [SUPPORTED])

    def test_an_existing_derived_skill_is_unchanged(self):
        findings = general_truth_findings(B_RESUME, B_FACTS)
        self.assertEqual([f["classification"] for f in _find(findings, where="skills[4]")], [DERIVED])


if __name__ == "__main__":
    unittest.main()
