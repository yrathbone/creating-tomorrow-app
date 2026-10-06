"""LinkedIn review vs saved Career Profile skills (plain code, no AI).

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest

from career.linkedin_compare import compare_skills

REVIEW = {
    "headline": {"current": "Payments & Treasury Solutions | ERP/API Integrations"},
    "about": {"suggested_revision": "I lead enterprise integrations and pre-sales solutioning."},
    "skills": {
        "clearly_demonstrated": [
            "Treasury Sales / Treasury Relationship Management - supported by multiple roles with revenue figures",
            "Pre-sales / Solutions Consulting - supported by the CashPro role description",
            "Team Leadership - supported by the Senior Treasury Services Director role",
        ],
        "possible_to_consider": ["Cross-functional Collaboration - the About section names Sales, Product and Engineering"],
        "needs_more_information": ["JavaScript - appears in Top skills but nothing in experience mentions it"],
    },
}


class CompareSkills(unittest.TestCase):
    def test_review_skills_missing_from_the_profile_are_suggested_as_clean_labels(self):
        out = compare_skills(REVIEW, ["Pre-sales", "Consultative Selling"])
        self.assertEqual(
            out["on_review_not_in_profile"],
            ["Treasury Sales", "Treasury Relationship Management", "Solutions Consulting", "Team Leadership", "Cross-functional Collaboration"],
        )

    def test_needs_more_information_items_are_not_suggested(self):
        out = compare_skills(REVIEW, [])
        self.assertNotIn("JavaScript", out["on_review_not_in_profile"])

    def test_skills_already_saved_are_not_suggested_even_with_different_wording(self):
        out = compare_skills(REVIEW, ["Team Leadership", "treasury sales experience", "Solutions Consulting"])
        self.assertNotIn("Team Leadership", out["on_review_not_in_profile"])
        self.assertNotIn("Treasury Sales", out["on_review_not_in_profile"])
        self.assertNotIn("Solutions Consulting", out["on_review_not_in_profile"])

    def test_profile_skills_never_mentioned_in_the_review_are_listed_for_linkedin(self):
        out = compare_skills(REVIEW, ["ERP/API Integrations", "Fintech", "Pre-sales", "Technical expertise"])
        self.assertEqual(out["in_profile_not_on_linkedin"], ["Fintech", "Technical expertise"])

    def test_bad_input_is_harmless(self):
        self.assertEqual(compare_skills({}, ["Fintech"]), {"on_review_not_in_profile": [], "in_profile_not_on_linkedin": ["Fintech"]})
        self.assertEqual(compare_skills({"skills": "x"}, []), {"on_review_not_in_profile": [], "in_profile_not_on_linkedin": []})
        self.assertEqual(compare_skills({"skills": {"clearly_demonstrated": [5, None]}}, [])["on_review_not_in_profile"], [])


if __name__ == "__main__":
    unittest.main()
