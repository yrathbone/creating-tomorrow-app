"""C-52 Scheduling and Zendesk (Data decision, 2026-11-15). Synthetic data only.

Scheduling: the general checker's narrowly scoped DERIVATION_RULES entry. DERIVED with the saved statement as its source; never
SUPPORTED; no title or credential promoted; verb and object must share one saved statement; hypothetical, negated or planned
statements never count. The job-targeted term-plan rules are not changed by this rule.

Zendesk: removing the headline mention does not touch a separately supported skill or an independently supported summary sentence.
"""
import os
import unittest

from career.resume_quality import general_truth_findings

SCHEDULED = "Scheduled weekly shift rotas for six agents."


def _facts(role_text, skills=("Team leadership", "Zendesk")):
    return {
        "roles": [{"id": 1, "title": "Customer Service Lead", "organization": "Fictional Organization Beta", "years": [2022, 2025],
                   "start": (2022, None), "end": (2025, None), "text": role_text}],
        "education": [],
        "skills": list(skills),
        "certifications": [],
    }


def _resume(skills=(), headline="", summary="", experience=()):
    return {"name": "Synthetic Member", "headline": headline, "summary": summary, "skills": list(skills),
            "experience": list(experience), "education": [], "certifications": []}


def _skill(findings, label):
    return [f for f in findings if f["where"].startswith("skills[") and f["text"] == label]


class SchedulingDerivationPositive(unittest.TestCase):
    def test_a_saved_shift_rota_statement_derives_scheduling_with_that_statement_as_source(self):
        f = general_truth_findings(_resume(skills=["Scheduling"]), _facts(SCHEDULED))
        item = _skill(f, "Scheduling")[0]
        self.assertEqual(item["classification"], "DERIVED")
        self.assertIn(SCHEDULED, item["source"])              # the complete saved statement is kept as the evidence
        self.assertIn("Customer Service Lead", item["source"])
        self.assertNotEqual(item["classification"], "SUPPORTED")  # never automatically SUPPORTED


class SchedulingNegativeContext(unittest.TestCase):
    def test_hypothetical_negated_or_planned_statements_do_not_support_scheduling(self):
        for text in ("Would schedule weekly rotas if hired.",
                     "Did not schedule shift changes for the team.",
                     "Plan to schedule rotas for the new team next year.",
                     "Never scheduled rotas; a colleague handled them."):
            with self.subTest(text=text):
                f = general_truth_findings(_resume(skills=["Scheduling"]), _facts(text))
                self.assertEqual(_skill(f, "Scheduling")[0]["classification"], "UNSUPPORTED")

    def test_the_verb_and_object_must_share_one_statement_and_unrelated_objects_do_not_count(self):
        # A scheduling verb with no rota, shift, roster or timetable object is not evidence of scheduling staff.
        f = general_truth_findings(_resume(skills=["Scheduling"]), _facts("Scheduled client meetings for the regional team."))
        self.assertEqual(_skill(f, "Scheduling")[0]["classification"], "UNSUPPORTED")
        # The verb in one statement and the object in another are not combined.
        f = general_truth_findings(_resume(skills=["Scheduling"]),
                                   _facts("Scheduled client reports for the regional team. Shift changes were approved by the lead."))
        self.assertEqual(_skill(f, "Scheduling")[0]["classification"], "UNSUPPORTED")


class SchedulingLineStatements(unittest.TestCase):
    """Saved bullets are often lines without a final stop. Each line is its own statement, so nothing runs into the next line."""

    def test_a_saved_shift_rota_line_without_a_full_stop_derives_scheduling_with_only_that_line(self):
        f = general_truth_findings(_resume(skills=["Scheduling"]),
                                   _facts("Led a team of 6 agents handling customer escalations\nScheduled weekly shift rotas for six agents"))
        item = _skill(f, "Scheduling")[0]
        self.assertEqual(item["classification"], "DERIVED")
        self.assertIn('"Scheduled weekly shift rotas for six agents"', item["source"])
        self.assertNotIn("Led a team", item["source"])

    def test_a_scheduling_verb_and_an_object_on_different_lines_are_not_combined(self):
        f = general_truth_findings(_resume(skills=["Scheduling"]),
                                   _facts("Scheduled client calls daily\nShift changes were approved by the lead"))
        self.assertEqual(_skill(f, "Scheduling")[0]["classification"], "UNSUPPORTED")


class SchedulingNoPromotion(unittest.TestCase):
    def test_the_scheduling_evidence_never_promotes_a_title_or_customer_escalations(self):
        # A headline that names a title is not established by the derived skill: no held title means it is not promoted to
        # SUPPORTED or DERIVED. It is UNSUPPORTED (the title has no evidence at all).
        f = general_truth_findings(_resume(skills=["Scheduling", "Customer escalations"], headline="Scheduling Manager"),
                                   _facts(SCHEDULED))
        headline = [x for x in f if x["where"] == "headline[0]"][0]
        self.assertEqual(headline["classification"], "UNSUPPORTED")
        # "Customer escalations" has no rule and no saved skill: it stays UNSUPPORTED.
        self.assertEqual(_skill(f, "Customer escalations")[0]["classification"], "UNSUPPORTED")


class ZendeskStatementScope(unittest.TestCase):
    def test_a_headline_mention_does_not_affect_the_saved_skill_or_the_matching_summary_sentence(self):
        facts = _facts("Led a team of 6 agents handling customer escalations on Zendesk.")
        summary = "Led a team of 6 agents handling customer escalations on Zendesk."
        f = general_truth_findings(_resume(skills=["Zendesk"], headline="Zendesk", summary=summary), facts)
        headline = [x for x in f if x["where"] == "headline[0]"][0]
        self.assertEqual(headline["classification"], "UNCERTAIN")          # the headline needs its own decision
        self.assertEqual(_skill(f, "Zendesk")[0]["classification"], "SUPPORTED")   # the saved skill is independent
        summary_item = [x for x in f if x["where"].startswith("summary[")][0]
        self.assertEqual(summary_item["classification"], "SUPPORTED")       # the exact saved sentence is independent


class ReviewCardScopeHint(unittest.TestCase):
    """The scope sentence appears in both review cards (general and job-targeted), so Remove is never read as global."""
    SENTENCE = "Remove applies only to this statement. Other mentions remain unless you review and remove them separately."

    def test_both_review_cards_say_that_remove_applies_only_to_the_statement(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "career", "login.html")
        with open(path, encoding="utf8") as fh:
            html = fh.read()
        self.assertEqual(html.count(self.SENTENCE), 2)


if __name__ == "__main__":
    unittest.main()
