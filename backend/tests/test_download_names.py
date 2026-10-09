"""Download file names: any person's name (accents, other alphabets, odd characters) must give a file, never an error."""
import unittest
from urllib.parse import unquote

from fastapi.testclient import TestClient

import main
from download_names import attachment_headers
from tests.test_resume_templates import SAMPLE

NAMES = ["Ada Lovelace", "Zoë Müller", "Nguyễn Văn An", "李明", "José O'Brien", 'Bad"Name', "line\r\nbreak: Set-Cookie: x=1",
         "../../etc/passwd", "a;b\\c/d", "", None, "   ", "x" * 500, "👩‍💻 Dev"]


def header(name, suffix="_Resume.docx", **kw):
    return attachment_headers(name, suffix, **kw)["Content-Disposition"]


class HeaderTests(unittest.TestCase):
    def test_the_header_is_always_plain_ascii_with_no_way_out(self):
        for name in NAMES:
            with self.subTest(name=name):
                value = header(name)
                value.encode("ascii")  # raises if any non-ASCII slipped in
                self.assertTrue(value.startswith('attachment; filename="'))
                self.assertNotIn("\r", value)
                self.assertNotIn("\n", value)
                self.assertEqual(value.count('"'), 2, "only the two quotes around the file name")
                first = value.split('filename="', 1)[1].split('"', 1)[0]
                for bad in ('/', '\\', ';', ' ', ':'):
                    self.assertNotIn(bad, first)
                self.assertTrue(first.endswith("_Resume.docx"))

    def test_plain_names_stay_plain_and_have_no_extra_part(self):
        self.assertEqual(header("Ada Lovelace"), 'attachment; filename="Ada_Lovelace_Resume.docx"')

    def test_accented_names_keep_their_letters_for_modern_browsers(self):
        value = header("Zoë Müller")
        self.assertIn('filename="Zoe_Muller_Resume.docx"', value)
        self.assertIn("filename*=UTF-8''", value)
        self.assertEqual(unquote(value.split("filename*=UTF-8''", 1)[1]), "Zoë_Müller_Resume.docx")

    def test_other_alphabets_fall_back_to_a_generic_ascii_name_but_keep_the_real_one(self):
        value = header("李明")
        self.assertIn('filename="Resume_Resume.docx"', value)
        self.assertEqual(unquote(value.split("filename*=UTF-8''", 1)[1]), "李明_Resume.docx")

    def test_blank_or_missing_names_use_the_fallback(self):
        for name in ("", None, "   ", "///"):
            self.assertEqual(header(name), 'attachment; filename="Resume_Resume.docx"')
        self.assertEqual(header(None, "_Right_Fit_Recap.docx", fallback="Candidate"), 'attachment; filename="Candidate_Right_Fit_Recap.docx"')

    def test_attack_text_is_reduced_to_harmless_letters(self):
        value = header("line\r\nbreak: Set-Cookie: x=1")
        self.assertNotIn("Set-Cookie:", value)
        self.assertNotIn("..", header("../../etc/passwd"))

    def test_very_long_names_are_cut(self):
        self.assertLess(len(header("x" * 500)), 200)


class RealRoutesTests(unittest.TestCase):
    """The same names through the real download routes (the bug was a 500 here)."""
    def setUp(self):
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_generate_gives_a_word_file_for_every_kind_of_name(self):
        for name in ("Ada Lovelace", "Zoë Müller", "Nguyễn Văn An", "李明", 'Bad"Name'):
            with self.subTest(name=name):
                res = self.client.post("/api/generate", json={"resume_data": dict(SAMPLE, name=name)})
                self.assertEqual(res.status_code, 200)
                self.assertIn("wordprocessingml", res.headers["content-type"])
                self.assertEqual(res.content[:2], b"PK")
                self.assertIn("attachment", res.headers["content-disposition"])

    def test_generate_with_no_name_at_all_still_works(self):
        data = {k: v for k, v in SAMPLE.items() if k != "name"}
        data["name"] = None
        self.assertEqual(self.client.post("/api/generate", json={"resume_data": data}).status_code, 200)

    def test_recap_gives_a_word_file_for_every_kind_of_name(self):
        report = {"match_level": "High", "match_rationale": "Strong fit."}
        for name in ("Zoë Müller", "李明", "Candidate"):
            with self.subTest(name=name):
                res = self.client.post("/api/recap", json={"match_report": report, "candidate_name": name})
                self.assertEqual(res.status_code, 200)
                self.assertIn("_Right_Fit_Recap.docx", res.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
