"""
Builds .docx files in memory (returns bytes rather than writing to disk,
since this runs inside a web request).

build_resume_bytes() produces the main resume, matching the Creating
Tomorrow template layout:

  NAME (bold, centered)
  Location | Phone | Email | LinkedIn   (centered)
  [shaded bar] PROFESSIONAL SUMMARY
  Summary paragraph(s)
  [shaded bar] CORE SKILLS & EXPERTISE
  Skills bullets, two columns by default (or one in ATS mode)
  [shaded bar] PROFESSIONAL EXPERIENCE
  Job title (bold) / Company, Location - Dates
  Bulleted achievements
  ... (repeat per job)
  [shaded bar] EDUCATION
  Bulleted degree/school lines

build_match_recap_bytes() produces a one-page downloadable recap of a
Right Fit comparison (match level, rationale, strengths, gaps, flags,
growth suggestions) using the same visual style.

build_resume_bytes() also recognizes a few optional keys used by Elevate
but harmless to every other tool (absent for them, so nothing changes):
  data["headline"]        - centered bold positioning line under contact
  data["skills_heading"]  - overrides the "CORE SKILLS & EXPERTISE" heading
                             text (Elevate uses "CORE EXPERTISE")
  data["certifications"]  - bulleted section rendered after Education, only
                             if non-empty
"""
import io

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HEADING_FILL = "CADCF2"
FONT_NAME = "Calibri"
FONT_SIZE = Pt(11)
PAGE_MARGIN = Inches(0.7)


def shade_paragraph(paragraph, fill_hex):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    pPr.append(shd)


def set_columns(section, num_cols):
    sectPr = section._sectPr
    cols = sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sectPr.append(cols)
    cols.set(qn("w:num"), str(num_cols))
    cols.set(qn("w:space"), "720")


def style_run(run, bold=False):
    run.font.name = FONT_NAME
    run.font.size = FONT_SIZE
    run.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), FONT_NAME)


def add_heading_bar(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    style_run(run, bold=True)
    shade_paragraph(p, HEADING_FILL)
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    style_run(run)
    return p


def set_page_geometry(section):
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin = PAGE_MARGIN
    section.right_margin = PAGE_MARGIN
    section.top_margin = PAGE_MARGIN
    section.bottom_margin = PAGE_MARGIN


def build_resume_bytes(data: dict, ats_mode: bool = False) -> bytes:
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = FONT_SIZE

    set_page_geometry(doc.sections[0])

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = p.add_run(data["name"])
    style_run(name_run, bold=True)
    p.add_run().add_break()
    contact_run = p.add_run(data["contact"])
    style_run(contact_run)

    if data.get("headline"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        headline_run = p.add_run(data["headline"])
        style_run(headline_run, bold=True)

    if data.get("summary"):
        add_heading_bar(doc, "PROFESSIONAL SUMMARY")

        summary = data["summary"]
        paragraphs = summary if isinstance(summary, list) else [summary]
        p = doc.add_paragraph()
        for i, para_text in enumerate(paragraphs):
            if i > 0:
                p.add_run().add_break()
                p.add_run().add_break()
            run = p.add_run(para_text)
            style_run(run)

    # Summary, skills, experience, and education sections only render if
    # there's actual content - an empty list/missing field used to still
    # print the heading bar with nothing underneath it (e.g. someone using
    # the start-from-scratch wizard who added zero experience entries got
    # an orphaned "PROFESSIONAL EXPERIENCE" heading followed immediately by
    # EDUCATION, or a resume with no source summary got an empty one).
    if data["skills"]:
        doc.add_section(WD_SECTION.CONTINUOUS)
        set_page_geometry(doc.sections[-1])
        add_heading_bar(doc, data.get("skills_heading", "CORE SKILLS & EXPERTISE"))

        doc.add_section(WD_SECTION.CONTINUOUS)
        set_page_geometry(doc.sections[-1])
        set_columns(doc.sections[-1], 1 if ats_mode else 2)
        for skill in data["skills"]:
            add_bullet(doc, skill)

    # Always start a fresh single-column section here, regardless of
    # whether there's experience content - this undoes the skills
    # section's column count (if it was 2), and EDUCATION below always
    # needs single column too.
    doc.add_section(WD_SECTION.CONTINUOUS)
    set_page_geometry(doc.sections[-1])
    set_columns(doc.sections[-1], 1)

    if data["experience"]:
        add_heading_bar(doc, "PROFESSIONAL EXPERIENCE")
        for i, job in enumerate(data["experience"]):
            p = doc.add_paragraph()
            if i > 0:
                p.paragraph_format.space_before = Pt(12)
            title_run = p.add_run(job["title"])
            style_run(title_run, bold=True)
            p.add_run().add_break()
            subtitle_run = p.add_run(job["subtitle"])
            style_run(subtitle_run)
            for bullet in job["bullets"]:
                add_bullet(doc, bullet)

    if data["education"]:
        edu_heading = add_heading_bar(doc, "EDUCATION")
        edu_heading.paragraph_format.space_before = Pt(6)
        for entry in data["education"]:
            add_bullet(doc, entry)

    certifications = data.get("certifications") or []
    if certifications:
        cert_heading = add_heading_bar(doc, "CERTIFICATIONS")
        cert_heading.paragraph_format.space_before = Pt(6)
        for entry in certifications:
            add_bullet(doc, entry)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def build_match_recap_bytes(match_report: dict, candidate_name: str) -> bytes:
    """One-page .docx recap of a Right Fit comparison: match level, the
    rationale, strengths, gaps, any "same word, different job" flags, and
    growth suggestions - a downloadable summary of what's shown on screen.
    """
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = FONT_SIZE

    set_page_geometry(doc.sections[0])

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = p.add_run(f"{candidate_name} — Right Fit Recap")
    style_run(name_run, bold=True)

    add_heading_bar(doc, "MATCH LEVEL")
    p = doc.add_paragraph()
    level_run = p.add_run(match_report.get("match_level", ""))
    style_run(level_run, bold=True)
    if match_report.get("match_rationale"):
        p = doc.add_paragraph()
        style_run(p.add_run(match_report["match_rationale"]))

    strengths = match_report.get("strengths") or []
    if strengths:
        add_heading_bar(doc, "WHAT'S ALREADY STRONG")
        for item in strengths:
            add_bullet(doc, item)

    gaps = match_report.get("required_qualification_gaps") or []
    if gaps:
        add_heading_bar(doc, "GAPS AGAINST WHAT THIS ROLE USUALLY REQUIRES")
        for gap in gaps:
            text = f"[{gap.get('status', '')}] {gap.get('requirement', '')} — {gap.get('explanation', '')}"
            add_bullet(doc, text)

    flags = match_report.get("same_word_different_job_flags") or []
    if flags:
        add_heading_bar(doc, '"SAME WORD, DIFFERENT JOB" FLAGS')
        for flag in flags:
            text = (
                f"“{flag.get('term', '')}” — on the resume: {flag.get('resume_meaning', '')}. "
                f"In the posting: {flag.get('posting_meaning', '')}. {flag.get('why_it_matters', '')}"
            )
            add_bullet(doc, text)

    growth = match_report.get("growth_suggestions") or []
    if growth:
        add_heading_bar(doc, "HOW TO GENUINELY GROW TOWARD THIS ROLE")
        for item in growth:
            add_bullet(doc, item)

    if match_report.get("note_on_better_fit_roles"):
        add_heading_bar(doc, "A NOTE ON FIT")
        p = doc.add_paragraph()
        style_run(p.add_run(match_report["note_on_better_fit_roles"]))

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
