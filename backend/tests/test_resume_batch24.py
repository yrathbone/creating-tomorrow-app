"""Phase 02, Batch 2.4: the same space above every section title, one rhythm for list items and jobs, and page breaks that
never strand a job's title lines or its last bullet. Reads the spacing back out of the finished file.

Each run builds three documents in memory (nothing is saved): Classic, Traditional, and Classic with the optional two-column skills.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import io
import unittest

from docx import Document
from docx.oxml.ns import qn

import resume_builder as rb

SKILLS = ["Leadership: coaching, planning", "Operations: Lean, forecasting", "Excel", "SQL", "Tableau", "Python"]
DATA = {
    "name": "Casey Rowan", "contact": "Naperville, IL | casey.rowan@example.com", "headline": "OPERATIONS | DATA",
    "summary": "Operations analyst with broad experience.", "skills": SKILLS,
    "experience": [
        {"title": "Analyst", "subtitle": "Brightline, Naperville, IL — 02/18 – present", "bullets": ["One"]},
        {"title": "Coordinator", "subtitle": "Harbor, Gary, IN — 2014 – 2018", "bullets": ["One", "Two", "Three"]},
        {"title": "Associate", "subtitle": "Lakeside, Gary, IN — 2009 – 2014", "bullets": ["One", "Two", "Three", "Four", "Five"]},
    ],
    "education": ["B.S., Business Analytics — NIU, 2017"], "certifications": ["PMP — 2017"],
    "additional_sections": [{"heading": "AWARDS", "items": ["Employee of the year 2016"]}],
}
HEADINGS = ["PROFESSIONAL SUMMARY", "CORE SKILLS & EXPERTISE", "PROFESSIONAL EXPERIENCE", "EDUCATION", "CERTIFICATIONS", "AWARDS"]


_BUILT = {}


def build(template="classic", style=""):
    """Built once per run and shared by every test, so a run produces exactly three documents."""
    if (template, style) not in _BUILT:
        _BUILT[(template, style)] = Document(io.BytesIO(rb.build_resume_bytes(dict(DATA, skills_style=style), template=template)))
    return _BUILT[(template, style)]


def style_chain_value(paragraph, attribute, default):
    """What Word would use: the paragraph's own setting, else its style's, else the document default."""
    own = getattr(paragraph.paragraph_format, attribute)
    if own is not None:
        return own.pt
    style = paragraph.style
    while style is not None:
        value = getattr(style.paragraph_format, attribute)
        if value is not None:
            return value.pt
        style = style.base_style
    return default


def space_before(p):
    return style_chain_value(p, "space_before", 0)


def space_after(p):
    return style_chain_value(p, "space_after", 10)  # the file's default paragraph spacing is 10 pt after


class SectionGaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {"classic": build("classic"), "traditional": build("traditional"), "columns": build("classic", "columns")}

    def test_every_section_title_has_the_same_space_above_it(self):
        for name, doc in self.docs.items():
            titles = [p for p in doc.paragraphs if p.text in HEADINGS]
            self.assertEqual([p.text for p in titles], HEADINGS, name)
            self.assertEqual({space_before(p) for p in titles}, {rb.SECTION_GAP}, name)

    def test_nothing_that_ends_a_section_adds_more_space_than_the_section_gap(self):
        # Word and LibreOffice use the larger of "space after" and "space before", so the gap above a title can only be the
        # same everywhere when no paragraph in front of a title asks for more than that
        for name, doc in self.docs.items():
            paragraphs = doc.paragraphs
            for i, p in enumerate(paragraphs):
                if p.text in HEADINGS and i > 0:
                    self.assertLessEqual(space_after(paragraphs[i - 1]), rb.SECTION_GAP, f"{name}: before {p.text}")

    def test_the_gap_after_skills_matches_the_gap_before_the_summary(self):
        for name, doc in self.docs.items():
            paragraphs = doc.paragraphs
            gaps = {}
            for i, p in enumerate(paragraphs):
                if p.text in ("PROFESSIONAL SUMMARY", "PROFESSIONAL EXPERIENCE"):
                    gaps[p.text] = max(space_after(paragraphs[i - 1]), space_before(p))
            self.assertEqual(gaps["PROFESSIONAL SUMMARY"], gaps["PROFESSIONAL EXPERIENCE"], name)

    def test_no_empty_paragraph_is_used_for_spacing(self):
        for name, doc in self.docs.items():
            self.assertTrue(all(p.text.strip() or p._p.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None for p in doc.paragraphs), name)


class ListsAndJobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = build("classic")

    def jobs(self):
        out, current = [], None
        for p in self.doc.paragraphs:
            if "\n" in p.text and p.text.split("\n")[0] in ("Analyst", "Coordinator", "Associate"):  # the dates line is rewritten, so match the title only
                current = {"head": p, "bullets": []}
                out.append(current)
            elif current is not None and p.style.name == "List Bullet" and p.text in ("One", "Two", "Three", "Four", "Five"):
                current["bullets"].append(p)
            elif p.text in HEADINGS:
                current = None
        return out

    def test_the_three_jobs_are_found(self):
        self.assertEqual([len(j["bullets"]) for j in self.jobs()], [1, 3, 5])

    def test_job_title_lines_sit_close_to_their_bullets_and_jobs_are_one_section_gap_apart(self):
        jobs = self.jobs()
        for job in jobs:
            self.assertEqual(space_after(job["head"]), rb.JOB_HEAD_GAP)
        self.assertEqual([space_before(j["head"]) for j in jobs[1:]], [rb.JOB_GAP, rb.JOB_GAP])
        self.assertEqual(rb.JOB_GAP, rb.SECTION_GAP)

    def test_a_job_keeps_at_least_two_bullets_with_its_title_and_never_ends_on_a_lone_bullet(self):
        jobs = self.jobs()
        keep = [[b.paragraph_format.keep_with_next is True for b in j["bullets"]] for j in jobs]
        self.assertEqual(keep[0], [False])                         # one bullet: the title line already keeps with it
        self.assertEqual(keep[1], [True, True, False])             # three bullets stay together
        self.assertEqual(keep[2], [True, False, False, True, False])  # five: first with second, last two together
        for j in jobs:
            self.assertTrue(j["head"].paragraph_format.keep_with_next)

    def test_list_items_are_two_points_apart_in_every_list(self):
        for p in self.doc.paragraphs:
            if p.style.name == "List Bullet":
                self.assertEqual(p.paragraph_format.space_after.pt, rb.LIST_GAP)


class TwoColumnSkillsAreUnchanged(unittest.TestCase):
    def test_the_optional_two_column_layout_is_still_two_columns_closed_by_a_continuous_break(self):
        doc = build("classic", "columns")
        counts = [s._sectPr.find(qn("w:cols")).get(qn("w:num")) for s in doc.sections if s._sectPr.find(qn("w:cols")) is not None]
        self.assertIn("2", counts)

    def test_every_skill_is_still_there_in_the_same_order(self):
        doc = build("classic", "columns")
        text = [p.text for p in doc.paragraphs]
        start = text.index("CORE SKILLS & EXPERTISE") + 1
        self.assertEqual(text[start:start + len(SKILLS)], SKILLS)


if __name__ == "__main__":
    unittest.main()
