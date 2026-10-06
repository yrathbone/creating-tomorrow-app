"""
Resume-driven Career Profile ingestion: upload a resume -> extract each
role, education entry, and certification -> run the same discovery-
interview loop Elevate already uses to surface under-described
experience -> the candidate confirms facts -> roles (plus confirmed
facts folded in), education, and certifications become real rows.

Two stages here, reusing elevate.py wherever the logic is genuinely
generic rather than resume-specific:
  start_resume_review() - restructures the resume into Experience-shaped
                   roles (not elevate's title/subtitle/bullets shape -
                   this app's Experience model has separate organization/
                   location/start_date/end_date columns), writes a short
                   analysis, and produces the first question batch.
  discover()        - imported UNCHANGED from elevate.py. The interview
                   loop doesn't care about the exact shape of resume_data
                   - it's only ever JSON-dumped into the prompt as
                   context - so this is genuine shared code, not a
                   reimplementation (see docs/CAREER_PROFILE_ARCHITECTURE_
                   AUDIT.md Section 8: elevate.py's pattern is the
                   strongest existing precedent for this feature).

No AI "finalize" rewrite step, unlike Elevate - there's no resume prose
to rewrite here. Saving confirmed roles/facts as real Experience rows
happens in career/routes.py, driven by the candidate's own review, not a
model call.
"""
import os

import anthropic

from elevate import discover, ElevateError  # noqa: F401 - re-exported for career/routes.py
from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")
MAX_TOKENS = 16000

RESTRUCTURE_SYSTEM_PROMPT = """You are Nova, a thoughtful career strategist reviewing someone's resume to help them build their Career Profile - a persistent record of their real career evidence, not a one-off document.

You are given raw text extracted from someone's resume (it may be in any order or layout - it's just extracted text).

Do six things:

1. Extract each ROLE (job, internship, or distinct position) faithfully into the schema below. Preserve all real content - do not invent, embellish, polish, or infer anything not in the source text. This is a faithful transcription step, not a rewrite: keep the candidate's own wording for bullets. Write start_date/end_date in numeric MM/YY format, keeping "Present"/"Current" as-is for an ongoing role. If a field genuinely isn't stated (e.g. no location given), leave it null rather than guessing.

2. Extract each EDUCATION entry (degree/program) faithfully - institution, degree, field_of_study, graduation_date. Only include what the resume actually states; leave a field null rather than guessing (e.g. don't infer a field of study from a degree name alone).

3. Extract each CERTIFICATION faithfully - name, issuer, date. Only real, explicitly stated certifications - never infer one from a job title or skill.

4. Write a short, warm, conversational ANALYSIS of the career areas you see - 2-4 sentences, naming the specific functional areas, industries, or types of work the resume shows evidence of. Never say or imply the resume is "bad," weak, or lacking - frame it as a strong starting point with more likely underneath it.

5. Infer 2-4 CATEGORIES of experience specific to THIS resume - not a generic checklist (for example: someone in banking might warrant categories like treasury products supported or senior client contacts; someone in technology might warrant systems/platforms used or stakeholder collaboration - generalize to whatever this resume's actual field is). For those categories, write the FIRST BATCH of 4-6 yes/no discovery questions - specific, resume-grounded questions about responsibilities, scope, or accomplishments that are common in this candidate's apparent field but that this resume doesn't currently mention. Each must be answerable honestly with yes/no. Never assume yes. 4-6 questions is the right size for a first batch, not more. This batch must never be empty - even a thorough, detailed resume always has more underneath it worth asking about (scope, scale, stakeholders, tools, outcomes); write at least 4 questions every time, no exceptions.

6. Extract the SKILLS the document explicitly lists (for example a Skills or Top Skills section, or a "Skills:" line - common on LinkedIn profile exports). Return each one as a short keyword exactly as listed, 1-4 words. Never infer a skill from a job duty or title; if the document lists no skills, return an empty list.

Call the submit_resume_review tool with the extracted roles, education, certifications, skills, analysis, categories, and first question batch. Do not respond with plain text."""

RESTRUCTURE_USER_PROMPT_TEMPLATE = """RESUME TEXT (raw extraction, order may be jumbled):
{resume_text}

Produce the extracted roles, analysis, categories, and first question batch as specified in the system prompt."""

RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid tool call. Please produce the full result again as one \
complete tool call.)"""

_ROLE_PROPS = {
    "title": {"type": "string"},
    "organization": {"type": "string"},
    "location": {"type": ["string", "null"]},
    "start_date": {"type": ["string", "null"], "description": "MM/YY format"},
    "end_date": {"type": ["string", "null"], "description": "MM/YY format, or 'Present' for an ongoing role"},
    "bullets": {"type": "array", "items": {"type": "string"}},
}

_EDUCATION_PROPS = {
    "institution": {"type": "string"},
    "degree": {"type": ["string", "null"]},
    "field_of_study": {"type": ["string", "null"]},
    "graduation_date": {"type": ["string", "null"], "description": "MM/YY format if stated"},
}

_CERTIFICATION_PROPS = {
    "name": {"type": "string"},
    "issuer": {"type": ["string", "null"]},
    "date": {"type": ["string", "null"], "description": "MM/YY format if stated"},
}

RESTRUCTURE_TOOL = {
    "name": "submit_resume_review",
    "description": "Submit the extracted roles, education, certifications, analysis, categories, and first question batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "roles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _ROLE_PROPS,
                    "required": ["title", "organization", "location", "start_date", "end_date", "bullets"],
                },
            },
            "education": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _EDUCATION_PROPS,
                    "required": ["institution", "degree", "field_of_study", "graduation_date"],
                },
            },
            "certifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _CERTIFICATION_PROPS,
                    "required": ["name", "issuer", "date"],
                },
            },
            "skills": {
                "type": "array",
                "description": "Skills the document explicitly lists, each a 1-4 word keyword. Empty if none are listed.",
                "items": {"type": "string"},
            },
            "analysis_summary": {"type": "string"},
            "categories": {"type": "array", "items": {"type": "string"}},
            "questions": {
                "type": "array",
                "minItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string"},
                        "question": {"type": "string"},
                    },
                    "required": ["id", "category", "question"],
                },
            },
        },
        "required": ["roles", "education", "certifications", "analysis_summary", "categories", "questions"],
    },
}


class IngestionError(Exception):
    pass


MAX_IMPORTED_SKILLS = 60
MAX_IMPORTED_SKILL_WORDS = 4


def clean_skills(raw) -> list[str]:
    """Skills listed in an imported document, as clean keywords: trimmed,
    1-4 words, no repeats (case-insensitive). Anything sentence-like or not
    text is dropped; the candidate still reviews every one before it is saved."""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = " ".join(item.split()).strip(" .;,-")
        key = name.lower()
        if not name or len(name) > 60 or len(name.split()) > MAX_IMPORTED_SKILL_WORDS or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out[:MAX_IMPORTED_SKILLS]


def _diagnose(category: str) -> None:
    print(f"[career.ingestion] attempt failed: {category}")


def _extract_tool_input(response) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [
        b for b in response.content
        if getattr(b, "type", None) == "tool_use" and b.name == "submit_resume_review"
    ]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    required = ("roles", "education", "certifications", "analysis_summary", "categories", "questions")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    # The prompt instructs at least 4 questions whenever there's a role to
    # ask about; enforce it in code too rather than trusting the model to
    # always follow the instruction (schema minItems alone isn't a
    # guarantee) - a candidate with real work history should never land on
    # an empty interview.
    if data.get("roles") and len(data.get("questions") or []) < 3:
        raise ValueError("too_few_questions")

    return data


def start_resume_review(resume_text: str, pdf_document_b64: str | None = None) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise IngestionError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = RESTRUCTURE_USER_PROMPT_TEMPLATE.format(
        resume_text=resume_text if resume_text.strip() else "(This document is a PDF of page images with no selectable text; read it from the attached pages.)"
    )

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        content = prompt_for_this_attempt
        if pdf_document_b64:
            # A PDF with no selectable text: its pages are read as images.
            content = [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_document_b64}},
                {"type": "text", "text": prompt_for_this_attempt},
            ]
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=RESTRUCTURE_SYSTEM_PROMPT,
                tools=[RESTRUCTURE_TOOL],
                tool_choice={"type": "tool", "name": "submit_resume_review"},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise IngestionError("We couldn't process that resume right now. Please try again.") from e

        log_usage("career_resume_start", response)
        try:
            data = _extract_tool_input(response)
            data["skills"] = clean_skills(data.get("skills"))
            return data
        except ValueError as e:
            _diagnose(str(e))

    raise IngestionError("We couldn't process that resume right now. Please try again.")
