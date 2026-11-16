"""C-52 stabilization (Data, 2026-11-15): F1 exact saved statements, F3 headline context. Synthetic data only.

F1: a sentence that repeats a saved line in the same saved context may be SUPPORTED. Changed actors, amounts, negation or titles are not.
F3: a saved skill does not justify the same words as a headline; the headline needs the member's confirmation, with the reason shown.
"""
import copy
import os
import unittest

from career import review_gate as rg
from career.resume_quality import HEADLINE_SKILL_EXPLANATION, general_truth_findings

FACTS = {
    "roles": [{"id": 1, "title": "Coordinator", "organization": "Fictional Organization Beta", "years": [2021, 2025],
               "start": (2021, 6), "end": (2025, 5),
               "text": "Led a team of 6 agents handling customer escalations\nReduced average response time by 25% through a new triage process"}],
    "education": [],
    "skills": ["Record keeping", "Team leadership"],
    "certifications": [],
}


def _resume(**kw):
    base = {"name": "Synthetic Member", "headline": "", "summary": "", "skills": [], "experience": [], "education": [], "certifications": []}
    base.update(kw)
    return base


def _at(findings, where):
    return [f for f in findings if f["where"] == where]


class ExactSavedStatementsF1(unittest.TestCase):
    def test_a_repeat_of_a_saved_line_in_the_same_role_is_supported(self):
        f = general_truth_findings(_resume(summary="Led a team of 6 agents handling customer escalations"), FACTS)
        self.assertEqual([x["classification"] for x in _at(f, "summary[0]")], ["SUPPORTED"])
        self.assertIn("Led a team of 6 agents handling customer escalations", _at(f, "summary[0]")[0]["source"])

    def test_the_second_saved_line_is_supported_too(self):
        f = general_truth_findings(_resume(summary="Reduced average response time by 25% through a new triage process"), FACTS)
        self.assertEqual([x["classification"] for x in _at(f, "summary[0]")], ["SUPPORTED"])

    def test_a_changed_actor_is_not_supported(self):
        f = general_truth_findings(_resume(summary="Managed a team of 6 agents handling customer escalations"), FACTS)
        self.assertNotEqual([x["classification"] for x in _at(f, "summary[0]")], ["SUPPORTED"])

    def test_a_changed_amount_is_not_supported(self):
        f = general_truth_findings(_resume(summary="Reduced average response time by 40% through a new triage process"), FACTS)
        self.assertNotEqual([x["classification"] for x in _at(f, "summary[0]")], ["SUPPORTED"])

    def test_an_added_negation_is_not_supported(self):
        f = general_truth_findings(_resume(summary="Did not lead a team of 6 agents handling customer escalations"), FACTS)
        self.assertNotEqual([x["classification"] for x in _at(f, "summary[0]")], ["SUPPORTED"])

    def test_a_partial_repeat_is_not_supported(self):
        f = general_truth_findings(_resume(summary="Led a team of 6 agents"), FACTS)
        self.assertNotEqual([x["classification"] for x in _at(f, "summary[0]")], ["SUPPORTED"])


class HeadlineSkillContextF3(unittest.TestCase):
    def test_a_headline_that_repeats_a_saved_skill_is_uncertain_with_the_reason(self):
        f = general_truth_findings(_resume(headline="Team leadership"), FACTS)
        item = _at(f, "headline[0]")[0]
        self.assertEqual(item["classification"], "UNCERTAIN")
        self.assertEqual(item["explanation"], HEADLINE_SKILL_EXPLANATION)

    def test_a_headline_matching_a_held_title_is_still_supported(self):
        f = general_truth_findings(_resume(headline="Coordinator"), FACTS)
        self.assertEqual([x["classification"] for x in _at(f, "headline[0]")], ["SUPPORTED"])

    def test_the_job_review_explains_a_headline_that_repeats_a_saved_skill(self):
        resume = _resume(headline="Team leadership | Customer Service Leadership",
                         experience=[{"title": "Coordinator", "subtitle": "", "bullets": []}])
        result = {"term_report": [{"term": "Team leadership", "support": "literal", "evidence": "Coordinator"}]}
        review = rg.job_review(copy.deepcopy(resume), result, FACTS, now=None)
        item = next(i for i in review["items"] if i["where"] == "headline[0]")
        self.assertEqual(item["classification"], "UNCERTAIN")
        self.assertEqual(item["explanation"], HEADLINE_SKILL_EXPLANATION)


class ReviewChangesStillCorrect(unittest.TestCase):
    """The Data 2026-11-15 F1/F3 corrections do not alter the round 8b review-change rules."""

    def test_no_change_is_reported_when_nothing_moved(self):
        row = {"where": "skills[0]", "text": "Record keeping", "classification": "SUPPORTED", "explanation": "x"}
        review = {"items": [], "supported": [row], "derived": [], "removed": []}
        self.assertEqual(rg.review_changes(review, review), [])



class FrontendStabilizationStatic(unittest.TestCase):
    """F6, F8, F9: static checks on the shipped frontend files (no production identifiers, the target size, the sign-off reason)."""

    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
    PROD_IDS = ("5rfhr0o7799aa41a5odrt9i9hd", "uLhNvjpep")

    def _read(self, rel):
        with open(os.path.join(self.ROOT, rel), encoding="utf8") as f:
            return f.read()

    def test_F9_no_production_cognito_identifier_is_written_in_any_frontend_file(self):
        for dirpath, _, names in os.walk(self.ROOT):
            for n in names:
                if n.endswith((".js", ".html", ".css")):
                    text = open(os.path.join(dirpath, n), encoding="utf8", errors="replace").read()
                    for pid in self.PROD_IDS:
                        self.assertNotIn(pid, text, f"{n} contains a production identifier")

    def test_F6_the_acknowledgement_label_is_a_44px_target_with_a_24px_box(self):
        css = self._read("career/dashboard-v8.css")
        self.assertIn("body.chrome-v6.dashboard-v4 .truth-ack { min-height: 44px", css)
        self.assertIn('.truth-ack input[type="checkbox"] { width: 24px; height: 24px', css)

    def test_F8_each_review_card_has_a_sign_off_reason_line_linked_to_its_button(self):
        html = self._read("career/login.html")
        for prefix in ("general-review", "job-review"):
            self.assertIn(f'id="{prefix}-signoff-why"', html)
        js = self._read("career/js/generalResumeReview.js")
        self.assertIn('setAttribute("aria-describedby", why.id)', js)



class RemovedSectionCollapsedF10(unittest.TestCase):
    """Data 2026-11-15 F10: the removed section is collapsed by default, shows its count, and has an accessible toggle."""

    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

    def test_each_card_has_a_collapsed_removed_panel_with_a_count_and_an_accessible_toggle(self):
        html = open(os.path.join(self.ROOT, "career", "login.html"), encoding="utf8").read()
        for prefix in ("general-review", "job-review"):
            self.assertIn(f'id="{prefix}-removed-count"', html)
            self.assertIn(f'id="{prefix}-removed-toggle"', html)
            self.assertIn(f'aria-expanded="false" aria-controls="{prefix}-removed-panel"', html)
            self.assertIn(f'id="{prefix}-removed-panel" class="truth-removed-panel" role="region"', html)
        js = open(os.path.join(self.ROOT, "career", "js", "generalResumeReview.js"), encoding="utf8").read()
        self.assertIn('state.removedOpen = !state.removedOpen', js)
        self.assertIn('toggle.setAttribute("aria-expanded"', js)


if __name__ == "__main__":
    unittest.main()
