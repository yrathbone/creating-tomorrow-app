"""C-52 closeout (Data, 2026-11-15): display-only narrowing of the evidence shown for SUPPORTED bullets. Synthetic data only.

The displayed source names the single saved line a bullet matches, with the role title and employer kept as context. The
classification, the hashes, the review decisions and the signed content do not change. Statements from different roles are not
combined, and an unsupported bullet stays unsupported.
"""
import unittest

from career.resume_quality import general_truth_findings
from career.review_gate import content_hash, facts_hash

ROLE_A = ("Customer Service Lead", "Sample Company")
ROLE_B = ("Shift Supervisor", "Fictional Organization Beta")


def _facts():
    return {
        "roles": [
            {"id": 1, "title": ROLE_A[0], "organization": ROLE_A[1], "years": [2022, 2025], "start": (2022, None), "end": (2025, None),
             "text": "Led a team of 6 agents handling customer escalations\nReduced average response time by 25% through a new triage process\n"
                     "Scheduled weekly shift rotas for six agents"},
            {"id": 2, "title": ROLE_B[0], "organization": ROLE_B[1], "years": [2019, 2021], "start": (2019, None), "end": (2021, None),
             "text": "Trained new staff on the cash drawer procedure\nOpened and closed the store each day"},
        ],
        "education": [],
        "skills": [],
        "certifications": [],
    }


def _resume(bullets_a=(), bullets_b=()):
    return {"name": "Synthetic Member", "headline": "", "summary": "", "skills": [], "education": [], "certifications": [],
            "experience": [
                {"title": ROLE_A[0], "subtitle": ROLE_A[1] + " · 2022 – 2025", "bullets": list(bullets_a)},
                {"title": ROLE_B[0], "subtitle": ROLE_B[1] + " · 2019 – 2021", "bullets": list(bullets_b)},
            ]}


def _bullet(findings, where):
    return [f for f in findings if f["where"] == where][0]


class DisplayedEvidenceIsTheSavedLine(unittest.TestCase):
    def test_a_supported_bullet_names_only_its_saved_line_with_role_context(self):
        f = general_truth_findings(_resume(bullets_a=["Scheduled weekly shift rotas for six agents"]), _facts())
        item = _bullet(f, "experience[0].bullets[0]")
        self.assertEqual(item["classification"], "SUPPORTED")
        self.assertIn('"Scheduled weekly shift rotas for six agents"', item["source"])
        self.assertIn(ROLE_A[0], item["source"])                  # role title kept as context
        self.assertNotIn("Led a team", item["source"])            # no other bullet of the same role
        self.assertNotIn("Reduced average", item["source"])

    def test_the_second_and_first_bullets_of_one_role_each_show_their_own_line(self):
        f = general_truth_findings(_resume(bullets_a=["Led a team of 6 agents handling customer escalations",
                                                      "Reduced average response time by 25% through a new triage process"]), _facts())
        self.assertIn('"Led a team of 6 agents handling customer escalations"', _bullet(f, "experience[0].bullets[0]")["source"])
        self.assertIn('"Reduced average response time by 25% through a new triage process"', _bullet(f, "experience[0].bullets[1]")["source"])


class RolesAreNotCombined(unittest.TestCase):
    def test_a_bullet_from_one_role_cites_only_that_role(self):
        f = general_truth_findings(_resume(bullets_b=["Opened and closed the store each day"]), _facts())
        item = _bullet(f, "experience[1].bullets[0]")
        self.assertEqual(item["classification"], "SUPPORTED")
        self.assertIn(ROLE_B[0], item["source"])
        self.assertNotIn(ROLE_A[0], item["source"])
        self.assertNotIn("Scheduled weekly", item["source"])


class UnsupportedStaysUnsupported(unittest.TestCase):
    def test_an_invented_amount_is_not_made_supported_by_the_display_change(self):
        f = general_truth_findings(_resume(bullets_a=["Reduced average response time by 40% through a new triage process"]), _facts())
        item = _bullet(f, "experience[0].bullets[0]")
        self.assertEqual(item["classification"], "UNSUPPORTED")
        self.assertEqual([x for x in f if x["where"] == "experience[0].bullets[0]" and x["classification"] == "SUPPORTED"], [])

    def test_a_bullet_built_from_words_of_two_lines_is_not_shown_as_one_saved_line(self):
        # Words from two different saved lines, in a new order, are not evidence-preserving. The rule is unchanged, so this stays
        # UNCERTAIN (or UNSUPPORTED), and no single line is shown as its evidence.
        f = general_truth_findings(_resume(bullets_a=["Triage process reduced average response time by 25% for six agents"]), _facts())
        item = _bullet(f, "experience[0].bullets[0]")
        self.assertNotEqual(item["classification"], "SUPPORTED")


class SignedContentUnchanged(unittest.TestCase):
    def test_the_hashes_depend_on_the_resume_and_facts_not_on_the_displayed_source(self):
        resume = _resume(bullets_a=["Scheduled weekly shift rotas for six agents"])
        facts = _facts()
        before = (content_hash(resume), facts_hash(facts))
        f = general_truth_findings(resume, facts)                 # the display change lives in the findings only
        self.assertTrue(any(x.get("source") for x in f))
        self.assertEqual(before, (content_hash(resume), facts_hash(facts)))


if __name__ == "__main__":
    unittest.main()
