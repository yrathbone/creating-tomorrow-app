"""
Shared resume-restructuring logic, extracted for the Career Profile
feature (docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md, Phase 0).

This is a generalization of a prompt that was duplicated, nearly
verbatim, across coach.py, upgrade.py, elevate.py, and prepare.py/
profile_review.py's resume-handling - each independently asks Claude to
take raw extracted resume text and restructure it (faithfully, no
rewriting) into the same basic shape. This module is that one shared
version.

IMPORTANT - Phase 0 scope: this module is NOT imported or called by
main.py or any of the six existing tool modules yet. It exists so
Phase 3 (resume ingestion into the Career Profile) has one correct
place to call, without touching any existing tool's behavior now. The
six tools keep their own independent restructuring logic unchanged
until/unless a later, separate, deliberate migration decides to have
them call this instead - that is explicitly not part of Phase 0.

Deliberately the FAITHFUL-TRANSCRIPTION shape (closest to elevate.py's
analyze_for_discovery(), not coach.py/upgrade.py's polish-and-rewrite
versions) - Career Profile ingestion should extract facts, not
editorialize, since every extracted fact starts as an unverified
candidate the person must confirm before it becomes real evidence
(see the "evidence-seeking, not deficiency-seeking" product principle -
this module's job is to surface what's there, not decide how it should
sound).
"""
import os

import anthropic

from llm_utils import describe_provider_error, log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")

# See coach.py for why this is larger than it looks like it should need
# to be: extended thinking eats a large, variable chunk of this budget
# before the actual structured output is produced.
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are restructuring raw text extracted from someone's resume (it may be in any order or layout - it's just extracted text) into a clean, structured shape.

This is a FAITHFUL TRANSCRIPTION task, not a rewrite. Preserve all real content exactly as the person wrote it - do not invent, embellish, polish, infer, or improve anything that isn't already in the source text. Keep the candidate's own wording. If contact info is incomplete, leave it out rather than guessing. Write every job's date range in numeric MM/YY format (e.g. "07/21 - 09/23"), converting from whatever format the source uses; keep "Present"/"Current" as-is for an ongoing role.

Call the submit_resume_structure tool with the restructured resume. Do not respond with plain text."""

USER_PROMPT_TEMPLATE = """RESUME TEXT (raw extraction, order may be jumbled):
{resume_text}

Restructure this faithfully as specified in the system prompt."""

RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid submit_resume_structure call. Please produce the full \
restructured resume again as one complete tool call.)"""

RESTRUCTURE_TOOL = {
    "name": "submit_resume_structure",
    "description": "Submit the faithfully restructured resume.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_data": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "contact": {"type": "string", "description": "City, ST | Phone | Email | LinkedIn - omit parts not found"},
                    "summary": {"type": "string", "description": "the candidate's own summary text, faithfully transcribed, not rewritten"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "experience": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "subtitle": {"type": "string", "description": "Company, City, ST — MM/YY – MM/YY"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "subtitle", "bullets"],
                        },
                    },
                    "education": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "contact", "skills", "experience", "education"],
            },
        },
        "required": ["resume_data"],
    },
}

REQUIRED_TOP_LEVEL_KEYS = ("resume_data",)


class ResumeIngestionError(Exception):
    pass


def _diagnose(category: str) -> None:
    print(f"[resume_ingestion] restructure attempt failed: {category}")


def _extract_tool_input(response) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [
        b for b in response.content
        if getattr(b, "type", None) == "tool_use" and b.name == "submit_resume_structure"
    ]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def restructure_resume(resume_text: str) -> dict:
    """Takes raw extracted resume text (from extractor.extract_text(),
    unchanged) and returns {"resume_data": {...}} - a faithful, unpolished
    structural transcription only. Not yet called by any route or tool -
    see the module docstring."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ResumeIngestionError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(resume_text=resume_text)

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[RESTRUCTURE_TOOL],
                tool_choice={"type": "tool", "name": "submit_resume_structure"},
                messages=[{"role": "user", "content": prompt_for_this_attempt}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error " + describe_provider_error(e))
            raise ResumeIngestionError("We couldn't process that resume right now. Please try again.") from e

        log_usage("resume_ingestion", response)
        try:
            return _extract_tool_input(response)
        except ValueError as e:
            _diagnose(str(e))

    raise ResumeIngestionError("We couldn't process that resume right now. Please try again.")
