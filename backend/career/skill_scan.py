"""
Career Profile skill/role-standard scan: reviews the WHOLE Career Profile
(not one job posting, not one freshly-uploaded resume) against what's
typically expected for the kinds of roles it represents, and interviews
the candidate on anything that looks standard for that field but isn't
yet reflected - things like "quota attainment," "CRM tools," or
"pipeline management" for a sales-flavored role, that the candidate may
genuinely have done but never wrote down.

Different from the other two gap-finding flows in this codebase, not a
duplicate of either:
  elevate.py / career/ingestion.py - gaps relative to what's missing from
                   ONE freshly uploaded resume's text, asked once at
                   ingestion time.
  career/job_match.py             - gaps relative to ONE specific job
                   posting's stated requirements.
  this module                     - gaps relative to general field/role
                   norms for the profile as a whole, runnable any time,
                   not tied to an upload or a posting.

The interview loop itself is elevate.discover(), reused via the existing
POST /api/career/job-discover route - no new discover() call needed here.
"""
import os

import anthropic

from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")
MAX_TOKENS = 16000

SCAN_SYSTEM_PROMPT = """You are Nova, a thoughtful career strategist reviewing someone's full Career Profile (their own already-confirmed roles, education, and certifications) to find real experience they likely have but haven't written down yet.

You are given a structured summary of the candidate's Career Profile.

This scan can be run more than once as a profile grows, so judge each run on its own merits rather than assuming there must be something new to ask:

1. Infer 0-4 CATEGORIES of skills, responsibilities, tools, or achievements that are STANDARD or commonly expected for the TYPES of roles this profile represents, but that the profile does NOT currently mention. Ground this in the specific roles/industries actually shown - not a generic checklist (for example: a sales-flavored role commonly involves quota attainment, pipeline/CRM management, or competitive positioning; a technical consulting role commonly involves specific platforms, stakeholder types, or delivery methodologies - generalize this idea to whatever this profile's actual fields are). The goal is catching real, plausible blind spots, not inventing generic filler or manufacturing a question just to have one.

2. For those categories, write a batch of yes/no discovery questions - specific, grounded in what this candidate's roles actually suggest, asking whether they've done something common for their field that their profile doesn't currently capture. Each must be answerable honestly with yes/no. Never assume yes. If the profile already looks well-rounded and thorough for the fields it represents, it is correct and expected to return FEW questions or an EMPTY list - that means the scan is genuinely done for now, not that you failed to find something. Never pad the list with a marginal or repetitive question just to avoid an empty result.

Call the submit_skill_scan tool with a short warm analysis summary, categories (may be empty), and the question batch (may be empty). Do not respond with plain text."""

SCAN_USER_PROMPT_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

Produce the analysis, categories, and first question batch as specified in the system prompt."""

RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid tool call. Please produce the full result again as one \
complete tool call.)"""

SCAN_TOOL = {
    "name": "submit_skill_scan",
    "description": "Submit the analysis summary, categories, and first question batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analysis_summary": {"type": "string"},
            "categories": {"type": "array", "items": {"type": "string"}},
            "questions": {
                "type": "array",
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
        "required": ["analysis_summary", "categories", "questions"],
    },
}


class SkillScanError(Exception):
    pass


def _diagnose(category: str) -> None:
    print(f"[career.skill_scan] attempt failed: {category}")


def _extract_tool_input(response) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [
        b for b in response.content
        if getattr(b, "type", None) == "tool_use" and b.name == "submit_skill_scan"
    ]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    required = ("analysis_summary", "categories", "questions")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def start_skill_scan(profile_text: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SkillScanError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = SCAN_USER_PROMPT_TEMPLATE.format(profile_text=profile_text)

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SCAN_SYSTEM_PROMPT,
                tools=[SCAN_TOOL],
                tool_choice={"type": "tool", "name": "submit_skill_scan"},
                messages=[{"role": "user", "content": prompt_for_this_attempt}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise SkillScanError("We couldn't run that scan right now. Please try again.") from e

        log_usage("career_skill_scan", response)
        try:
            return _extract_tool_input(response)
        except ValueError as e:
            _diagnose(str(e))

    raise SkillScanError("We couldn't run that scan right now. Please try again.")
