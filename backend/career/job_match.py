"""
Career-Profile-driven job comparison: paste a job description -> compare
it against the WHOLE Career Profile (not just one uploaded resume) ->
interview on any gaps (reusing elevate.py's discover() again, same as
career/ingestion.py already does) -> build a tailored resume from real
profile evidence, in resume_builder.py's existing format.

Two model calls here, reusing established patterns rather than inventing
new ones:
  compare_to_job()      - mirrors coach.py's (Right Fit) match_report
                   schema exactly, so match_level/strengths/gaps mean the
                   same thing everywhere in this codebase. Input differs
                   from coach.py: a structured summary of the whole
                   Career Profile, not one raw resume text.
  build_tailored_resume() - mirrors elevate.py's finalize_elevate():
                   original evidence + confirmed interview facts are the
                   ONLY source of truth, nothing invented. Produces
                   resume_data in the exact shape build_resume_bytes()
                   already expects, so /api/generate (unchanged) can turn
                   it into the .docx.

The gap-interview loop itself is elevate.discover(), imported unchanged
via career.ingestion - not reimplemented here.
"""
import os

import anthropic

from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")
MAX_TOKENS = 16000

COMPARE_SYSTEM_PROMPT = """You are Nova, a career coach helping someone understand how their verified Career Profile compares to a specific job posting, and where it's worth digging for evidence they haven't captured yet.

You are given a structured summary of the candidate's Career Profile (real roles, education, and certifications they've already confirmed - not a raw resume) and the text of a job posting.

Do three things:

1. ASSESS how well the Career Profile matches the job posting, honestly, as "Low", "Average", or "High", the way a discerning human recruiter would - NOT by counting keyword overlap and NOT with a letter grade or numeric score. Call out cases where a word or phrase appears in both the profile and the posting but means something different in context (e.g. "cash management" at a retail bank branch vs. as a corporate treasury product). Be calibrated: most real comparisons should land as "Average". Be encouraging in TONE, never by inflating the ASSESSMENT. Frame any gap as "not yet evidenced" or "worth exploring," never as something wrong with the person - an unconfirmed qualification is a statement about the profile's current evidence, not about them.

2. Identify REQUIRED QUALIFICATION GAPS - job requirements the profile doesn't yet clearly evidence, each marked "missing" or "partial" with a plain explanation.

3. For the gaps you found, write a FIRST BATCH of 4-6 yes/no discovery questions to find out if the candidate actually has relevant experience that just isn't in their profile yet - specific and grounded in this posting's actual requirements, never generic. Each must be answerable honestly with yes/no. Never assume yes. This batch must never be empty when there are real gaps to explore.

4. Extract a short JOB TITLE label for this posting - e.g. "Senior Software Engineer at Acme Corp" - or a brief descriptive phrase if the posting doesn't plainly state a title/employer (e.g. "Retail Store Manager role").

Call the submit_job_comparison tool with your complete analysis. Do not respond with plain text."""

COMPARE_USER_PROMPT_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

TARGET JOB POSTING:
{job_description}

Produce the comparison as specified in the system prompt."""

RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid tool call. Please produce the full result again as one \
complete tool call.)"""

MATCH_REPORT_PROPS = {
    "match_level": {"type": "string", "enum": ["Low", "Average", "High"]},
    "match_rationale": {"type": "string", "description": "1-2 sentences"},
    "strengths": {"type": "array", "items": {"type": "string"}},
    "required_qualification_gaps": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "requirement": {"type": "string"},
                "status": {"type": "string", "enum": ["missing", "partial"]},
                "explanation": {"type": "string"},
            },
            "required": ["requirement", "status", "explanation"],
        },
    },
}

COMPARE_TOOL = {
    "name": "submit_job_comparison",
    "description": "Submit the job title label, match assessment, gaps, categories, and first discovery-question batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_title": {
                "type": "string",
                "description": "A short label for this posting, e.g. 'Senior Software Engineer at Acme Corp' - or a brief descriptive phrase if the posting doesn't plainly state a title/employer.",
            },
            "match_report": {
                "type": "object",
                "properties": MATCH_REPORT_PROPS,
                "required": ["match_level", "match_rationale", "strengths", "required_qualification_gaps"],
            },
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
        "required": ["job_title", "match_report", "categories", "questions"],
    },
}


BUILD_RESUME_SYSTEM_PROMPT = """You are Nova, an expert executive resume writer, building a resume tailored to a specific job from a candidate's verified Career Profile. You are given the candidate's FULL Career Profile (real roles, education, certifications) plus a target job posting, plus any CONFIRMED FACTS they approved during a gap-interview about this posting - together these are the ONLY source of truth. Nothing else may be added.

FACTUAL SAFETY RULES (non-negotiable):
Never invent skills, technologies, employers, job titles, metrics, revenue, team sizes, certifications, education, products, responsibilities, leadership scope, client types, awards, or years of experience. Only the supplied Career Profile content and confirmed facts may appear. If something is uncertain, leave it out.
Never promote participation into ownership: if source text says "supported" do not write "led"; if it says "partnered with" do not write "owned".

TAILORING (this is a selection/prioritization task, not a rewrite of the facts):
Select and order skills and bullets that are most relevant to this specific job posting - the Career Profile likely has more history than belongs on one resume; use judgment about what to foreground, but do not drop an entire role that's part of the candidate's real background. Fold each confirmed fact's bullet into the single most relevant existing role (matching by category, timing, or context) - never invent a new employer or role to hold it.

WRITING STYLE:
Senior, polished, confident, concise, human. Avoid repetitive AI resume language such as "results-driven," "dynamic," "highly motivated," "proven track record," or "hard-working" unless truly appropriate given the evidence.

Build the resume:
1. A POSITIONING HEADLINE: 2-3 short pipe-separated capitalized phrases capturing the candidate's professional identity relevant to this job, supported only by their real experience.
2. A PROFESSIONAL SUMMARY (3-5 lines) connecting their real background to this specific posting.
3. SKILLS: a list of skills/expertise phrases drawn from the Career Profile plus whatever the confirmed facts demonstrate, prioritized for relevance to this posting.
4. EXPERIENCE: each role's bullets, prioritized and polished for relevance to this posting, confirmed facts folded into the right role.
5. EDUCATION and CERTIFICATIONS: pass through from the Career Profile unchanged.

Call the submit_tailored_resume tool with the resume. Do not respond with plain text."""

BUILD_RESUME_USER_PROMPT_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

TARGET JOB POSTING:
{job_description}

CONFIRMED FACTS FROM THE GAP INTERVIEW (approved by the candidate - the only new content allowed):
{facts_text}

CANDIDATE NAME: {name}
CANDIDATE CONTACT LINE: {contact}

Produce the tailored resume as specified in the system prompt."""

_RESUME_EXPERIENCE_PROPS = {
    "title": {"type": "string"},
    "subtitle": {"type": "string", "description": "Organization, City, ST — MM/YY – MM/YY"},
    "bullets": {"type": "array", "items": {"type": "string"}},
}

BUILD_RESUME_TOOL = {
    "name": "submit_tailored_resume",
    "description": "Submit the tailored resume in the standard format.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_data": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "contact": {"type": "string"},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "experience": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": _RESUME_EXPERIENCE_PROPS,
                            "required": ["title", "subtitle", "bullets"],
                        },
                    },
                    "education": {"type": "array", "items": {"type": "string"}},
                    "certifications": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "contact", "headline", "summary", "skills", "experience", "education"],
            },
        },
        "required": ["resume_data"],
    },
}


class JobMatchError(Exception):
    pass


def _diagnose(category: str) -> None:
    print(f"[career.job_match] attempt failed: {category}")


def _extract_tool_input(response, tool_name: str, required_keys: tuple) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [
        b for b in response.content
        if getattr(b, "type", None) == "tool_use" and b.name == tool_name
    ]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def _call_with_retry(label: str, system_prompt: str, user_prompt: str, tool: dict, extract) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise JobMatchError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": prompt_for_this_attempt}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise JobMatchError("We couldn't complete this comparison right now. Please try again.") from e

        log_usage(label, response)
        try:
            return extract(response)
        except ValueError as e:
            _diagnose(str(e))

    raise JobMatchError("We couldn't complete this comparison right now. Please try again.")


def compare_to_job(profile_text: str, job_description: str) -> dict:
    user_prompt = COMPARE_USER_PROMPT_TEMPLATE.format(profile_text=profile_text, job_description=job_description)
    return _call_with_retry(
        "career_job_compare",
        COMPARE_SYSTEM_PROMPT,
        user_prompt,
        COMPARE_TOOL,
        extract=lambda r: _extract_tool_input(r, "submit_job_comparison", ("job_title", "match_report", "categories", "questions")),
    )


def build_tailored_resume(profile_text: str, job_description: str, confirmed_facts: list, name: str, contact: str) -> dict:
    facts_text = (
        "\n".join(f"- ({f.get('category', '')}) {f.get('bullet_text', '')}" for f in confirmed_facts)
        if confirmed_facts
        else "(none confirmed - use only the Career Profile itself)"
    )
    user_prompt = BUILD_RESUME_USER_PROMPT_TEMPLATE.format(
        profile_text=profile_text,
        job_description=job_description,
        facts_text=facts_text,
        name=name,
        contact=contact,
    )
    return _call_with_retry(
        "career_job_build_resume",
        BUILD_RESUME_SYSTEM_PROMPT,
        user_prompt,
        BUILD_RESUME_TOOL,
        extract=lambda r: _extract_tool_input(r, "submit_tailored_resume", ("resume_data",)),
    )
