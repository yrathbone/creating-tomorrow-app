"""Skills read from an imported document (e.g. a LinkedIn PDF) are cleaned to
short keywords before the candidate reviews them.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import unittest

from career.ingestion import clean_skills


class CleanSkills(unittest.TestCase):
    def test_keywords_are_kept_trimmed_and_deduped_case_insensitively(self):
        out = clean_skills(["  Consultative Selling ", "consultative selling", "ERP Integrations;", "Pre-sales", ""])
        self.assertEqual(out, ["Consultative Selling", "ERP Integrations", "Pre-sales"])

    def test_sentences_and_non_text_are_dropped(self):
        out = clean_skills(["Led a team of five engineers across three regions", 42, None, {"name": "x"}, "APIs"])
        self.assertEqual(out, ["APIs"])

    def test_missing_or_wrong_type_returns_empty(self):
        self.assertEqual(clean_skills(None), [])
        self.assertEqual(clean_skills("Sales"), [])

    def test_list_is_capped(self):
        self.assertEqual(len(clean_skills([f"Skill {i}" for i in range(200)])), 60)


if __name__ == "__main__":
    unittest.main()
