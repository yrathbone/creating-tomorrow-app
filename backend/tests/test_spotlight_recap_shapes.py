"""The Spotlight Word download must still build when the AI returns a section in an unexpected shape."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resume_builder import build_profile_review_recap_bytes  # noqa: E402


class SpotlightRecapShapes(unittest.TestCase):
    def assertBuilds(self, review):
        data = build_profile_review_recap_bytes(review)
        self.assertTrue(data.startswith(b"PK"), "not a Word (zip) file")

    def test_sections_as_plain_text(self):
        self.assertBuilds({
            "headline": "Logistics coordinator",
            "about": "Short about text.",
            "experience": "Worked on logistics.",
            "skills": "Excel, SAP",
            "strengths": ["Reliable", {"title": "Organised", "evidence": "Ran a warehouse team."}],
            "suggested_full_profile": {"headline": "x", "about": "y", "experience": ["Coordinator at Acme", {"title": "Clerk", "organization": "Beta", "bullets": "one line"}]},
        })

    def test_list_items_as_sentences(self):
        self.assertBuilds({
            "headline": {"supplied": True, "suggested": "New headline", "could_be_clearer": "Say more about results."},
            "about": {"supplied": True, "could_be_clearer": ["Tighten the opening.", {"text": "Add a metric."}]},
            "experience": {"supplied": True, "suggested_improvements": None},
            "skills": {"needs_more_information": "Which tools?"},
            "strengths": "one strength as text",
        })

    def test_missing_and_empty_values(self):
        self.assertBuilds({"insufficient_information": False, "strengths": None, "headline": None, "about": ""})
        self.assertBuilds({})


if __name__ == "__main__":
    unittest.main()
