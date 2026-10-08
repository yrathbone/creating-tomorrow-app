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

build_resume_bytes(data, ats_mode, template) takes a layout name: "classic" (the layout above,
unchanged), "modern" or "traditional". Unknown names quietly mean classic. See TEMPLATES.

build_match_recap_bytes() produces a one-page downloadable recap of a
Right Fit comparison (match level, rationale, strengths, gaps, flags,
growth suggestions) using the same visual style.

build_resume_bytes() also recognizes a few optional keys, harmless to any
tool that doesn't set them (absent for them, so nothing changes):
  data["headline"]           - centered bold positioning line under contact
  data["skills_heading"]     - overrides the "CORE SKILLS & EXPERTISE"
                                heading text (Elevate/Refine use "CORE
                                EXPERTISE")
  data["certifications"]     - bulleted section rendered after Education,
                                only if non-empty (used by Elevate)
  data["additional_sections"] - a list of {"heading": str, "items": [str]}
                                sections rendered after Education/
                                Certifications, one heading bar + bulleted
                                items per entry, only for entries with a
                                non-empty items list (used by Refine to
                                preserve things like Awards & Recognition,
                                Licenses, Languages, Military Service,
                                Professional Affiliations, Publications,
                                Patents, or Security Clearances found in the
                                source resume)
"""
import io

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HEADING_FILL = "CADCF2"
FONT_NAME = "Calibri"
FONT_SIZE = Pt(11)
PAGE_MARGIN = Inches(0.7)

CENTER = WD_ALIGN_PARAGRAPH.CENTER
LEFT = WD_ALIGN_PARAGRAPH.LEFT

# Resume layouts. The words are identical in every layout; only the look changes.
#   classic     - the original Creating Tomorrow look: centered, shaded section bars (unchanged).
#   modern      - left-aligned, a large navy name, section titles with a thin navy line under them.
#   traditional - serif font, centered name, section titles with a thin black line under them.
# "heading" is "bar" (shaded paragraph) or "rule" (a line under the title).
TEMPLATES = {
    "classic": {
        "font": "Calibri", "size": 11, "name_size": 11, "name_color": None,
        "contact_size": 11, "contact_color": None, "align": CENTER,
        "heading": "bar", "heading_fill": "CADCF2", "heading_color": None,
        "heading_align": CENTER, "rule_color": None, "heading_before": None,
    },
    "modern": {
        "font": "Calibri", "size": 10.5, "name_size": 22, "name_color": "1F3A8A",
        "contact_size": 10, "contact_color": "4B5565", "align": LEFT,
        "heading": "rule", "heading_fill": None, "heading_color": "1F3A8A",
        "heading_align": LEFT, "rule_color": "1F3A8A", "heading_before": 10,
    },
    "traditional": {
        "font": "Times New Roman", "size": 11, "name_size": 18, "name_color": None,
        "contact_size": 10.5, "contact_color": None, "align": CENTER,
        "heading": "rule", "heading_fill": None, "heading_color": None,
        "heading_align": LEFT, "rule_color": "000000", "heading_before": 8,
    },
}
DEFAULT_TEMPLATE = "classic"


def resolve_template(name) -> dict:
    """The layout for a name from the request; anything unknown quietly means Classic."""
    return TEMPLATES.get(name if isinstance(name, str) else "", TEMPLATES[DEFAULT_TEMPLATE])


def shade_paragraph(paragraph, fill_hex):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    pPr.append(shd)


# Where a bottom border belongs among a paragraph's properties (Word wants them in this order).
_AFTER_PBDR = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid",
    "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
    "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)


def underline_paragraph(paragraph, color_hex):
    """A thin line under the paragraph (used by the Modern and Traditional section titles)."""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.insert_element_before(pBdr, *_AFTER_PBDR)


def set_columns(section, num_cols):
    sectPr = section._sectPr
    cols = sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sectPr.append(cols)
    cols.set(qn("w:num"), str(num_cols))
    cols.set(qn("w:space"), "720")


def style_run(run, bold=False, tpl=None, size=None, color=None):
    tpl = tpl or TEMPLATES[DEFAULT_TEMPLATE]
    run.font.name = tpl["font"]
    run.font.size = Pt(size if size is not None else tpl["size"])
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), tpl["font"])


def add_heading_bar(doc, text, tpl=None):
    tpl = tpl or TEMPLATES[DEFAULT_TEMPLATE]
    p = doc.add_paragraph()
    p.alignment = tpl["heading_align"]
    run = p.add_run(text)
    style_run(run, bold=True, tpl=tpl, color=tpl["heading_color"])
    if tpl["heading"] == "bar":
        shade_paragraph(p, tpl["heading_fill"])
    else:
        p.paragraph_format.space_before = Pt(tpl["heading_before"] or 8)
        p.paragraph_format.space_after = Pt(3)
        underline_paragraph(p, tpl["rule_color"])
    return p


def add_bullet(doc, text, tpl=None):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    style_run(run, tpl=tpl)
    return p


def add_skill_line(doc, text, tpl=None):
    """A compact skills line like "Payments & Integration: API Connectivity, ISO 20022"
    - the part before the first colon (if any) is the bold group label."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    label, sep, rest = text.partition(":")
    if sep and len(label) <= 40:
        style_run(p.add_run(label + ":"), bold=True, tpl=tpl)
        style_run(p.add_run(rest), tpl=tpl)
    else:
        style_run(p.add_run(text), tpl=tpl)
    return p


def set_page_geometry(section):
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.left_margin = PAGE_MARGIN
    section.right_margin = PAGE_MARGIN
    section.top_margin = PAGE_MARGIN
    section.bottom_margin = PAGE_MARGIN


def build_resume_bytes(data: dict, ats_mode: bool = False, template: str = DEFAULT_TEMPLATE) -> bytes:
    tpl = resolve_template(template)
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = tpl["font"]
    normal.font.size = Pt(tpl["size"])

    set_page_geometry(doc.sections[0])

    p = doc.add_paragraph()
    p.alignment = tpl["align"]
    name_run = p.add_run(data["name"])
    style_run(name_run, bold=True, tpl=tpl, size=tpl["name_size"], color=tpl["name_color"])
    p.add_run().add_break()
    contact_run = p.add_run(data["contact"])
    style_run(contact_run, tpl=tpl, size=tpl["contact_size"], color=tpl["contact_color"])

    if data.get("headline"):
        p = doc.add_paragraph()
        p.alignment = tpl["align"]
        p.paragraph_format.space_before = Pt(4)
        headline_run = p.add_run(data["headline"])
        style_run(headline_run, bold=True, tpl=tpl)

    if data.get("summary"):
        add_heading_bar(doc, "PROFESSIONAL SUMMARY", tpl)

        summary = data["summary"]
        paragraphs = summary if isinstance(summary, list) else [summary]
        p = doc.add_paragraph()
        for i, para_text in enumerate(paragraphs):
            if i > 0:
                p.add_run().add_break()
                p.add_run().add_break()
            run = p.add_run(para_text)
            style_run(run, tpl=tpl)

    # Summary, skills, experience, and education sections only render if
    # there's actual content - an empty list/missing field used to still
    # print the heading bar with nothing underneath it (e.g. someone using
    # the start-from-scratch wizard who added zero experience entries got
    # an orphaned "PROFESSIONAL EXPERIENCE" heading followed immediately by
    # EDUCATION, or a resume with no source summary got an empty one).
    if data["skills"]:
        doc.add_section(WD_SECTION.CONTINUOUS)
        set_page_geometry(doc.sections[-1])
        add_heading_bar(doc, data.get("skills_heading", "CORE SKILLS & EXPERTISE"), tpl)

        doc.add_section(WD_SECTION.CONTINUOUS)
        set_page_geometry(doc.sections[-1])
        # "grouped" = a few compact "Label: skill, skill" lines (single column)
        # instead of one bullet per skill in two columns.
        grouped = data.get("skills_style") == "grouped"
        set_columns(doc.sections[-1], 1 if (ats_mode or grouped) else 2)
        for skill in data["skills"]:
            (add_skill_line if grouped else add_bullet)(doc, skill, tpl)

    # Always start a fresh single-column section here, regardless of
    # whether there's experience content - this undoes the skills
    # section's column count (if it was 2), and EDUCATION below always
    # needs single column too.
    doc.add_section(WD_SECTION.CONTINUOUS)
    set_page_geometry(doc.sections[-1])
    set_columns(doc.sections[-1], 1)

    if tpl["heading"] == "rule" and data["skills"]:
        # a small gap under the skills list (the underlined section titles would otherwise sit tight against it)
        gap = doc.add_paragraph()
        gap.paragraph_format.space_after = Pt(0)
        style_run(gap.add_run(" "), tpl=tpl, size=4)

    if data["experience"]:
        add_heading_bar(doc, "PROFESSIONAL EXPERIENCE", tpl)
        for i, job in enumerate(data["experience"]):
            p = doc.add_paragraph()
            if i > 0:
                p.paragraph_format.space_before = Pt(12)
            title_run = p.add_run(job["title"])
            style_run(title_run, bold=True, tpl=tpl)
            p.add_run().add_break()
            subtitle_run = p.add_run(job["subtitle"])
            style_run(subtitle_run, tpl=tpl)
            for bullet in job["bullets"]:
                add_bullet(doc, bullet, tpl)

    if data["education"]:
        edu_heading = add_heading_bar(doc, "EDUCATION", tpl)
        edu_heading.paragraph_format.space_before = Pt(6)
        for entry in data["education"]:
            add_bullet(doc, entry, tpl)

    certifications = data.get("certifications") or []
    if certifications:
        cert_heading = add_heading_bar(doc, "CERTIFICATIONS", tpl)
        cert_heading.paragraph_format.space_before = Pt(6)
        for entry in certifications:
            add_bullet(doc, entry, tpl)

    for section in data.get("additional_sections") or []:
        items = section.get("items") or []
        if not items:
            continue
        section_heading = add_heading_bar(doc, section.get("heading", ""), tpl)
        section_heading.paragraph_format.space_before = Pt(6)
        for entry in items:
            add_bullet(doc, entry, tpl)

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


def build_profile_review_recap_bytes(review: dict) -> bytes:
    """One-page .docx summary of a Spotlight review: signature strengths,
    the concrete suggested headline/About rewrites (the parts someone can
    actually copy and use), a consolidated list of ways to strengthen the
    profile, and - when there was enough material - a sample of what an
    updated profile could look like altogether, at the end. Deliberately
    tighter than the full on-screen section-by-section breakdown, so the
    download is something worth acting on rather than a re-read of the
    whole page.
    """
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = FONT_SIZE

    set_page_geometry(doc.sections[0])

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = p.add_run("Spotlight — LinkedIn Profile Review")
    style_run(name_run, bold=True)

    if review.get("insufficient_information"):
        add_heading_bar(doc, "MORE INFORMATION NEEDED")
        p = doc.add_paragraph()
        style_run(p.add_run(
            review.get("insufficient_information_message")
            or "There wasn't enough profile information supplied for a useful review."
        ))
        buffer = io.BytesIO()
        doc.save(buffer)
        return buffer.getvalue()

    strengths = review.get("strengths") or []
    if strengths:
        add_heading_bar(doc, "SIGNATURE STRENGTHS")
        for item in strengths:
            p = doc.add_paragraph()
            title_run = p.add_run(item.get("title", ""))
            style_run(title_run, bold=True)
            if item.get("evidence"):
                ev = doc.add_paragraph()
                style_run(ev.add_run(item["evidence"]))

    headline = review.get("headline") or {}
    if headline.get("supplied") and headline.get("suggested"):
        add_heading_bar(doc, "SUGGESTED HEADLINE")
        p = doc.add_paragraph()
        style_run(p.add_run(headline["suggested"]))

    about = review.get("about") or {}
    if about.get("supplied") and about.get("suggested_revision"):
        add_heading_bar(doc, "SUGGESTED ABOUT SECTION")
        p = doc.add_paragraph()
        style_run(p.add_run(about["suggested_revision"]))

    ways_to_strengthen = []
    if headline.get("supplied"):
        ways_to_strengthen.extend(headline.get("could_be_clearer") or [])
    if about.get("supplied"):
        ways_to_strengthen.extend(about.get("could_be_clearer") or [])
    experience = review.get("experience") or {}
    if experience.get("supplied"):
        ways_to_strengthen.extend(experience.get("suggested_improvements") or [])
    skills = review.get("skills") or {}
    ways_to_strengthen.extend(skills.get("needs_more_information") or [])

    if ways_to_strengthen:
        add_heading_bar(doc, "WAYS TO STRENGTHEN THIS PROFILE")
        for item in ways_to_strengthen:
            add_bullet(doc, item)

    sample = review.get("suggested_full_profile")
    if sample:
        add_heading_bar(doc, "SAMPLE UPDATED PROFILE")
        p = doc.add_paragraph()
        style_run(p.add_run(
            "One way to put these suggestions together - feel free to use, adapt, or ignore any of it."
        ))
        if sample.get("headline"):
            p = doc.add_paragraph()
            style_run(p.add_run("Headline: "), bold=True)
            style_run(p.add_run(sample["headline"]))
        if sample.get("about"):
            hp = doc.add_paragraph()
            style_run(hp.add_run("About"), bold=True)
            p = doc.add_paragraph()
            style_run(p.add_run(sample["about"]))
        for role in sample.get("experience") or []:
            title = role.get("title", "")
            org = role.get("organization", "")
            p = doc.add_paragraph()
            style_run(p.add_run(f"{title} — {org}" if org else title), bold=True)
            for bullet in role.get("bullets") or []:
                add_bullet(doc, bullet)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
