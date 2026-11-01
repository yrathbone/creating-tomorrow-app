"""Phase 02, Batch 2.1: structure and safety of the generated Word files.

The files must (1) have real Word headings and honest file properties, (2) contain no empty filler paragraphs, and
(3) survive messy input (control characters, wrong value types, missing parts) without crashing or turning a string into
one bullet per character, while well-formed content keeps exactly the same words in the same order.

Everything here builds small files in memory from invented data. Run from the backend folder:
    py -3.12 -m unittest discover -s tests -t .
"""
import io
import re
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient

import abuse_guard
import main
import resume_builder as rb

LAYOUTS = ("classic", "modern", "traditional")

PERSON = {
    "name": "Jordan Ellis",
    "contact": "Chicago, IL | jordan.ellis@example.com | (555) 010-0142",
    "headline": "Customer Service | Teamwork",
    "summary": ["Dependable student with two years of food-service experience.", "Ready to grow."],
    "skills": ["Customer service: greeting guests, taking orders", "Teamwork: opening and closing routines"],
    "skills_style": "grouped",
    "experience": [
        {"title": "Crew Member", "subtitle": "Corner Café, Chicago, IL — 06/24 – Present", "bullets": ["Served about 60 guests per shift", "Trained 3 new crew members"]},
        {"title": "Volunteer Tutor", "subtitle": "Lincoln Library — 09/24 – 05/25", "bullets": ["Helped younger students with reading"]},
    ],
    "education": ["Lincoln High School — Diploma expected 06/2027"],
    "certifications": ["CPR and First Aid — Red Cross (2025)"],
    "additional_sections": [{"heading": "LANGUAGES", "items": ["English", "Spanish"]}],
}
SECTION_TITLES = ["PROFESSIONAL SUMMARY", "CORE SKILLS & EXPERTISE", "PROFESSIONAL EXPERIENCE", "EDUCATION", "CERTIFICATIONS", "LANGUAGES"]


def build(data=PERSON, template="classic", ats=False):
    return rb.build_resume_bytes(data, ats_mode=ats, template=template)


def doc_of(blob):
    return Document(io.BytesIO(blob))


def parts(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml")}


def texts(doc):
    return [p.text for p in doc.paragraphs]


class RealHeadings(unittest.TestCase):
    def test_every_section_title_is_a_word_heading_in_every_layout(self):
        for template in LAYOUTS:
            for ats in (False, True):
                with self.subTest(template=template, ats=ats):
                    doc = doc_of(build(template=template, ats=ats))
                    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
                    self.assertEqual(headings, SECTION_TITLES)

    def test_only_section_titles_use_the_heading_style(self):
        doc = doc_of(build())
        others = [p.text for p in doc.paragraphs if p.style.name == "Heading 1" and p.text not in SECTION_TITLES]
        self.assertEqual(others, [])

    def test_sections_with_nothing_in_them_get_no_heading(self):
        sparse = dict(PERSON, skills=[], experience=[], education=[], certifications=[], additional_sections=[], summary=None)
        for template in LAYOUTS:
            doc = doc_of(build(sparse, template))
            self.assertEqual([p for p in doc.paragraphs if p.style.name == "Heading 1"], [], template)

    def test_the_heading_style_carries_the_layouts_look_not_word_stock_blue(self):
        looks = {"classic": ("Calibri", 11.0), "modern": ("Calibri", 10.5), "traditional": ("Times New Roman", 11.0)}
        for template, (font, size) in looks.items():
            with self.subTest(template=template):
                blob = build(template=template)
                style = doc_of(blob).styles["Heading 1"]
                xml = parts(blob)["word/styles.xml"]
                heading = re.search(r'<w:style [^>]*w:styleId="Heading1".*?</w:style>', xml, re.S).group(0)
                self.assertEqual(style.font.size.pt, size)
                self.assertTrue(style.font.bold)
                self.assertNotIn("Theme", heading, "no theme fonts or theme colours left in the heading style")
                self.assertNotIn("365F91", heading, "the stock blue is gone")
                self.assertIn(f'w:ascii="{font}"', heading)
                self.assertEqual(style.paragraph_format.space_before.pt, 0)
                self.assertEqual(style.paragraph_format.space_after.pt, 10)

    def test_headings_and_job_titles_stay_with_what_follows_them(self):
        doc = doc_of(build())
        self.assertTrue(doc.styles["Heading 1"].paragraph_format.keep_with_next)
        self.assertTrue(doc.styles["Heading 1"].paragraph_format.keep_together)
        job_lines = [p for p in doc.paragraphs if p.text.startswith("Crew Member") or p.text.startswith("Volunteer Tutor")]
        self.assertEqual(len(job_lines), 2)
        for p in job_lines:
            self.assertTrue(p.paragraph_format.keep_with_next, p.text)

    def test_classic_heading_properties_are_in_schema_order(self):
        for p in doc_of(build()).paragraphs:
            if p.style.name == "Heading 1":
                order = [child.tag.split("}")[1] for child in p._p.pPr]
                self.assertEqual(order, ["pStyle", "shd", "spacing", "jc"] if "spacing" in order else ["pStyle", "shd", "jc"], p.text)


class HonestProperties(unittest.TestCase):
    def test_title_author_and_dates_describe_this_resume(self):
        for template in LAYOUTS:
            blob = build(template=template)
            core = doc_of(blob).core_properties
            self.assertEqual(core.title, "Jordan Ellis — Résumé")
            self.assertEqual(core.author, "Jordan Ellis")
            self.assertEqual(core.comments, "")
            self.assertEqual(core.last_modified_by, "")
            now = datetime.now(timezone.utc)
            for stamp in (core.created, core.modified):
                stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)  # python-docx versions differ on this
                self.assertLess(abs(now - stamp), timedelta(minutes=5), "dated now, not 2013")

    def test_nothing_in_the_file_properties_says_python_docx(self):
        for blob in (build(), rb.build_match_recap_bytes({"match_level": "High"}, "Jordan"), rb.build_profile_review_recap_bytes({"strengths": [{"title": "A", "evidence": "b"}]})):
            for name, xml in parts(blob).items():
                if name.startswith("docProps/"):
                    self.assertNotIn("python-docx", xml, name)

    def test_a_resume_without_a_name_still_gets_a_sensible_title_and_no_author(self):
        core = doc_of(build(dict(PERSON, name=None))).core_properties
        self.assertEqual(core.title, "Résumé")
        self.assertEqual(core.author, "")

    def test_the_default_language_is_english_and_a_valid_tag_changes_it(self):
        blob = build()
        self.assertIn('<w:lang w:val="en-US"', parts(blob)["word/styles.xml"])
        self.assertEqual(doc_of(blob).core_properties.language, "en-US")
        spanish = build(dict(PERSON, lang="es-US"))
        self.assertIn('<w:lang w:val="es-US"', parts(spanish)["word/styles.xml"])
        self.assertEqual(doc_of(spanish).core_properties.language, "es-US")
        for tag in ("zh-Hans-CN", "fr", "pt-BR"):
            self.assertIn(f'w:val="{tag}"', parts(build(dict(PERSON, lang=tag)))["word/styles.xml"], tag)

    def test_a_bad_language_tag_means_english_never_an_error_or_injected_markup(self):
        for bad in ("x; evil", "", None, 123, "en_US", "e", "a" * 40, '"><w:evil/>', ["es"]):
            with self.subTest(bad=bad):
                xml = parts(build(dict(PERSON, lang=bad)))["word/styles.xml"]
                self.assertIn('<w:lang w:val="en-US"', xml)
                self.assertNotIn("evil", xml)

    def test_the_recap_documents_get_real_headings_and_titles_too(self):
        recap = doc_of(rb.build_match_recap_bytes({"match_level": "High", "match_rationale": "x", "strengths": ["a"]}, "Jordan"))
        self.assertEqual(recap.core_properties.title, "Jordan — Right Fit Recap")
        self.assertEqual([p.text for p in recap.paragraphs if p.style.name == "Heading 1"], ["MATCH LEVEL", "WHAT'S ALREADY STRONG"])
        review = doc_of(rb.build_profile_review_recap_bytes({"strengths": [{"title": "T", "evidence": "e"}]}))
        self.assertEqual(review.core_properties.title, "Spotlight — LinkedIn Profile Review")
        self.assertEqual([p.text for p in review.paragraphs if p.style.name == "Heading 1"], ["SIGNATURE STRENGTHS"])


class NoFillerParagraphs(unittest.TestCase):
    def test_no_empty_paragraphs_anywhere(self):
        for template in LAYOUTS:
            for style in ("grouped", ""):
                for ats in (False, True):
                    with self.subTest(template=template, style=style, ats=ats):
                        doc = doc_of(build(dict(PERSON, skills_style=style), template, ats))
                        empties = [i for i, p in enumerate(doc.paragraphs) if not p.text.strip()]
                        self.assertEqual(empties, [])

    def test_a_single_column_resume_is_one_section(self):
        for template in LAYOUTS:
            for kwargs in ({"ats": True, "data": dict(PERSON, skills_style="")}, {"ats": False, "data": PERSON}):
                self.assertEqual(len(doc_of(build(template=template, **kwargs)).sections), 1, (template, kwargs["ats"]))

    def test_the_two_column_skills_list_is_its_own_section_between_two_single_column_ones(self):
        data = dict(PERSON, skills_style="columns", skills=["One", "Two", "Three", "Four"])
        for template in LAYOUTS:
            with self.subTest(template=template):
                doc = doc_of(build(data, template))
                columns = [s._sectPr.find(qn("w:cols")) for s in doc.sections]
                self.assertEqual(len(doc.sections), 3)
                self.assertEqual([c.get(qn("w:num")) if c is not None else None for c in columns], [None, "2", None])
                self.assertEqual([s.start_type for s in doc.sections][1:], [rb.WD_SECTION.CONTINUOUS] * 2)
                # the breaks sit on real paragraphs: the skills title and the last skill
                carriers = [p.text for p in doc.paragraphs if p._p.pPr is not None and p._p.pPr.find(qn("w:sectPr")) is not None]
                self.assertEqual(carriers, ["CORE SKILLS & EXPERTISE", "Four"])

    def test_the_same_words_come_out_in_the_same_order(self):
        # a golden check on well-formed data: nothing added, dropped or reordered
        expected = [
            "Jordan Ellis", "Chicago, IL | jordan.ellis@example.com | (555) 010-0142", "Customer Service | Teamwork",
            "PROFESSIONAL SUMMARY", "Dependable student with two years of food-service experience.\n\nReady to grow.",
            "CORE SKILLS & EXPERTISE", "Customer service: greeting guests, taking orders", "Teamwork: opening and closing routines",
            "PROFESSIONAL EXPERIENCE", "Crew Member\nCorner Café, Chicago, IL — Jun 2024 – Present", "Served about 60 guests per shift", "Trained 3 new crew members",
            "Volunteer Tutor\nLincoln Library — Sep 2024 – May 2025", "Helped younger students with reading",
            "EDUCATION", "Lincoln High School — Diploma expected 06/2027", "CERTIFICATIONS", "CPR and First Aid — Red Cross (2025)", "LANGUAGES", "English", "Spanish",
        ]
        for template in LAYOUTS:
            self.assertEqual(texts(doc_of(build(template=template))), expected, template)


class MessyInput(unittest.TestCase):
    def text_of(self, data, template="classic"):
        doc = doc_of(build(data, template))
        return "\n".join(texts(doc)), doc

    def test_control_characters_never_stop_the_build_and_never_reach_the_file(self):
        bad = {"nul": "\x00", "vt": "\x0b", "unit-sep": "\x1f", "delete": "\x7f", "non-char": "￾", "lone-surrogate": chr(0xD800)}
        for label, ch in bad.items():
            with self.subTest(char=label):
                data = dict(PERSON, name=f"Na{ch}me", summary=f"Sum{ch}mary", skills=[f"Ski{ch}ll"], skills_style="",
                            experience=[{"title": f"Ti{ch}tle", "subtitle": f"Su{ch}b", "bullets": [f"Bu{ch}llet"]}], education=[f"Ed{ch}u"], certifications=[f"Ce{ch}rt"])
                text, _ = self.text_of(data)
                for control in ("\x00", "\x1f", "\x7f", "￾", chr(0xD800)):
                    self.assertNotIn(control, text)
                self.assertIn("Name", text.replace("\n", "") if label == "vt" else text) if label != "vt" else None

    def test_a_vertical_tab_from_word_becomes_a_line_break(self):
        text, doc = self.text_of(dict(PERSON, experience=[{"title": "T", "subtitle": "S", "bullets": ["first part\x0bsecond part"]}]))
        self.assertIn("first part\nsecond part", text)
        xml = parts(build(dict(PERSON, experience=[{"title": "T", "subtitle": "S", "bullets": ["first part\x0bsecond part"]}])))["word/document.xml"]
        self.assertIn("<w:br/>", xml)

    def test_invisible_characters_are_removed_but_script_joiners_are_kept(self):
        text, _ = self.text_of(dict(PERSON, summary="zero​width ﻿mark ‮override word⁠joiner"))
        self.assertIn("zerowidth mark override wordjoiner", text)
        kept, _ = self.text_of(dict(PERSON, summary="می‌خواهم and \U0001F468‍\U0001F4BB emoji"))
        self.assertIn("‌", kept)  # Persian needs the zero-width non-joiner
        self.assertIn("‍", kept)  # emoji sequences need the zero-width joiner

    def test_a_bullet_character_typed_by_the_person_is_not_doubled(self):
        text, doc = self.text_of(dict(PERSON, experience=[{"title": "T", "subtitle": "S", "bullets": ["• Led a team", "●  Cut costs", "- keeps its hyphen"]}]))
        self.assertIn("Led a team", texts(doc))
        self.assertIn("Cut costs", texts(doc))
        self.assertIn("- keeps its hyphen", texts(doc))

    def test_a_string_where_a_list_belongs_is_one_item_not_one_per_character(self):
        data = dict(PERSON, skills="Python, SQL", skills_style="columns", education="One school", certifications="One cert",
                    experience=[{"title": "T", "subtitle": "S", "bullets": "One long bullet."}])
        doc = doc_of(build(data))
        bullets = [p.text for p in doc.paragraphs if p.style.name == "List Bullet"]
        self.assertEqual(bullets, ["Python, SQL", "One long bullet.", "One school", "One cert", "English", "Spanish"])

    def test_wrong_value_types_become_text_or_are_skipped(self):
        data = dict(PERSON, experience=[{"title": "T", "subtitle": "S", "bullets": [2024, None, "", "  ", 3.5, "ok"]}, 42, None, ["x"], "Just a job title"])
        doc = doc_of(build(data))
        bullets = [p.text for p in doc.paragraphs if p.style.name == "List Bullet" and p.text in ("2024", "3.5", "ok")]
        self.assertEqual(bullets, ["2024", "3.5", "ok"])
        self.assertIn("Just a job title", texts(doc))
        self.assertEqual([p.text for p in doc.paragraphs if not p.text.strip()], [])

    def test_missing_parts_leave_out_their_section_instead_of_failing(self):
        for missing in ("subtitle", "bullets", "title"):
            job = {k: v for k, v in PERSON["experience"][0].items() if k != missing}
            doc = doc_of(build(dict(PERSON, experience=[job])))
            self.assertIn("PROFESSIONAL EXPERIENCE", texts(doc), missing)
        for key in ("education", "skills", "experience", "summary", "certifications", "headline", "contact", "additional_sections"):
            data = {k: v for k, v in PERSON.items() if k != key}
            doc = doc_of(build(data))
            self.assertIn("Jordan Ellis", doc.paragraphs[0].text, key)

    def test_a_job_with_a_title_but_no_subtitle_has_no_stray_line_break(self):
        doc = doc_of(build(dict(PERSON, experience=[{"title": "Solo Title", "bullets": ["b"]}])))
        self.assertIn("Solo Title", texts(doc))
        self.assertNotIn("Solo Title\n", "\n".join(texts(doc)).replace("Solo Title\nb", ""))

    def test_nonsense_instead_of_a_resume_still_gives_a_valid_empty_file(self):
        for junk in (None, "text", [], 7, {}, {"name": None}):
            with self.subTest(junk=junk):
                doc = doc_of(build(junk))
                self.assertEqual([p for p in doc.paragraphs if p.style.name == "Heading 1"], [])

    def test_big_and_odd_content_still_builds(self):
        data = dict(PERSON, experience=[{"title": f"Job {i}", "subtitle": "S", "bullets": ["b"] * 6} for i in range(200)])
        self.assertEqual(sum(1 for p in doc_of(build(data)).paragraphs if p.style.name == "List Bullet"), 1200 + 1 + 1 + 2)
        long = "word " * 1000
        self.assertIn(long.strip(), "\n".join(texts(doc_of(build(dict(PERSON, experience=[{"title": "T", "subtitle": "S", "bullets": [long]}]))))))

    def test_html_and_xml_looking_text_is_kept_as_plain_text(self):
        text, _ = self.text_of(dict(PERSON, name='Test <Person> & "Sons"', summary="<b>bold</b> &amp; <w:evil/>"))
        self.assertIn('Test <Person> & "Sons"', text)
        self.assertIn("<b>bold</b> &amp; <w:evil/>", text)
        self.assertNotIn("<w:evil/>", parts(build(dict(PERSON, summary="<w:evil/>")))["word/document.xml"].replace("&lt;w:evil/&gt;", ""))

    def test_the_recap_documents_survive_control_characters_too(self):
        report = {"match_level": "Hi\x0bgh", "match_rationale": "a\x00b", "strengths": ["s\x1f1", None, 5], "required_qualification_gaps": [{"status": "missing", "requirement": "r\x0b", "explanation": "e"}]}
        self.assertTrue(doc_of(rb.build_match_recap_bytes(report, "Na\x00me")).paragraphs)
        self.assertTrue(doc_of(rb.build_match_recap_bytes("not a dict", None)).paragraphs)
        self.assertTrue(doc_of(rb.build_profile_review_recap_bytes({"strengths": [{"title": "T\x0b", "evidence": "e\x00"}], "headline": {"supplied": True, "suggested": "h\x1f"}})).paragraphs)
        self.assertTrue(doc_of(rb.build_profile_review_recap_bytes(None)).paragraphs is not None)


class DownloadRouteWithMessyInput(unittest.TestCase):
    """What a person's download does when the saved resume has the problems above: a normal file, not a server error."""

    def setUp(self):
        abuse_guard.reset()
        self.addCleanup(abuse_guard.reset)
        self.client = TestClient(main.app)

    def post(self, data, **extra):
        return self.client.post("/api/generate", json={"resume_data": data, **extra})

    def test_a_control_character_gives_a_file_not_a_500(self):
        res = self.post(dict(PERSON, summary="a\x0bb", experience=[{"title": "T", "subtitle": "S", "bullets": ["x\x00y"]}]))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("a\nb", "\n".join(texts(doc_of(res.content))))

    def test_missing_subtitle_gives_a_file_not_a_500(self):
        res = self.post(dict(PERSON, experience=[{"title": "T", "bullets": ["x"]}]))
        self.assertEqual(res.status_code, 200, res.text)

    def test_a_number_in_a_bullet_gives_a_file_not_a_500(self):
        res = self.post(dict(PERSON, experience=[{"title": "T", "subtitle": "S", "bullets": [2024]}]))
        self.assertEqual(res.status_code, 200, res.text)

    def test_the_required_top_level_parts_are_still_checked_with_a_plain_400(self):
        res = self.post({k: v for k, v in PERSON.items() if k != "education"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("education", res.json()["detail"])

    def test_the_language_can_be_sent_and_the_file_carries_it(self):
        res = self.post(dict(PERSON, lang="es-US"))
        self.assertEqual(res.status_code, 200)
        self.assertIn('<w:lang w:val="es-US"', parts(res.content)["word/styles.xml"])


if __name__ == "__main__":
    unittest.main()
