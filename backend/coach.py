"""
Right Fit: the core comparison tool. Takes raw extracted text from someone's
old resume plus a target job posting, and produces (1) their resume
restructured into our clean schema, (2) an honest Low/Average/High match
assessment, and (3) a short list of reflective yes/no questions aimed at
surfacing real experience they didn't think to write down.

Deliberately NOT keyword matching - this calls the Claude API to reason
about the comparison the way a human career coach would.

Structured output: the analysis is requested via a forced tool call
(tool_choice) rather than asking the model to emit raw JSON text. This is
the SDK's own schema-constrained mechanism - the model's tool "input" is
generated and validated against ANALYSIS_TOOL's input_schema directly, so
there's no markdown-fence stripping, no hunting for the first "{" and last
"}" in a wall of text, and no risk of a stray unescaped character silently
breaking a hand-rolled parser. If the first attempt doesn't come back as a
complete, valid tool call (e.g. cut off by hitting max_tokens), one retry
is made before giving up - see analyze().
"""
import os

import anthropic

from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")

# Generous headroom: this model spends a meaningful chunk of its output
# budget on extended thinking before it produces the actual analysis (observed
# ~2800-3200 thinking tokens in practice), and the full resume_data +
# match_report + reflective_questions payload for a detailed resume/posting
# pair can itself run several thousand tokens. The previous 8000 cap left too
# little room for both and caused the response to be cut off mid-object.
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are Nova, a career coach helping a job seeker \
honestly rebuild their resume for a specific job posting. You are given \
raw text extracted from someone's OLD resume (it may be in any order or \
layout - it's just extracted text) and the text of a job posting they \
want to apply for.

Do three things:

1. RESTRUCTURE the old resume into the required schema. Preserve all \
real content faithfully. Do not invent, embellish, or infer anything \
that isn't actually in the source text. If contact info is incomplete, \
leave it out rather than guessing. Keep bullet points close to their \
original wording, but you may tighten grammar/phrasing for clarity. \
Write every job's date range in numeric MM/YY format (e.g. "07/21 – \
09/23"), converting from whatever format the source uses; keep "Present" \
or "Current" as-is (do not turn it into a date) for an ongoing role.

2. ASSESS how well this resume matches the job posting, honestly, as \
"Low", "Average", or "High", the way a discerning human recruiter would - \
NOT by counting keyword overlap and NOT with a letter grade or numeric \
score. Call out cases where a word or phrase appears on both the resume \
and the posting but means something different in context (e.g. "cash \
management" at a retail bank branch vs. as a corporate treasury product) \
- these are the traps that make keyword-matching tools misleading. Be \
calibrated: most real comparisons should land as "Average". Reserve \
"High" for a genuinely strong match against the posting's actual \
requirements, and "Low" for a fundamentally different field or missing \
multiple required qualifications. Be encouraging in TONE, never by \
inflating the ASSESSMENT.

3. Based on the gaps you found, write 3-6 REFLECTIVE QUESTIONS a coach \
would ask the candidate to find out if they have relevant unlisted \
experience related to the job posting's requirements. Each question must \
be answerable honestly with yes/no. For each, specify EXACTLY what would \
be added to the resume if the answer is yes - either one new skill, or \
one new bullet under a specific existing job (reference it by its index \
in the "experience" array you produced in step 1, 0 = most recent/first \
listed - omit experience_index entirely for a "skill" addition). Never \
assume yes. Never invent experience - only ask.

Call the submit_analysis tool with your complete analysis. Do not \
respond with plain text."""

USER_PROMPT_TEMPLATE = """OLD RESUME TEXT (raw extraction, order may be jumbled):
{resume_text}

TARGET JOB POSTING:
{job_posting}

Produce the analysis as specified in the system prompt."""

RETRY_NOTE = """

(Note: a prior attempt at this same analysis did not come back as a \
complete, valid submit_analysis call. Please produce the full analysis - \
restructured resume, match assessment, and reflective questions - as one \
complete submit_analysis tool call.)"""

# Mirrors the schema previously described in prose in the system prompt,
# now expressed as the tool's actual input_schema so the model's output is
# generated against it directly instead of us parsing free-text JSON.
ANALYSIS_TOOL = {
    "name": "submit_analysis",
    "description": "Submit the completed resume restructuring, match assessment, and reflective questions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_data": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "contact": {"type": "string", "description": "City, ST | Phone | Email | LinkedIn - omit parts not found"},
                    "summary": {"type": "string", "description": "one paragraph, or omit if none existed in the source"},
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
            "match_report": {
                "type": "object",
                "properties": {
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
                    "same_word_different_job_flags": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "term": {"type": "string"},
                                "resume_meaning": {"type": "string"},
                                "posting_meaning": {"type": "string"},
                                "why_it_matters": {"type": "string"},
                            },
                            "required": ["term", "resume_meaning", "posting_meaning", "why_it_matters"],
                        },
                    },
                    "growth_suggestions": {"type": "array", "items": {"type": "string"}},
                    "note_on_better_fit_roles": {"type": "string", "description": "1-2 sentences, if this posting is a stretch"},
                },
                "required": ["match_level", "match_rationale", "strengths", "required_qualification_gaps", "growth_suggestions"],
            },
            "reflective_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "question": {"type": "string"},
                        "add_if_yes": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["skill", "bullet"]},
                                "experience_index": {"type": "integer", "description": "only meaningful when type is bullet"},
                                "text": {"type": "string"},
                            },
                            "required": ["type", "text"],
                        },
                    },
                    "required": ["id", "question", "add_if_yes"],
                },
            },
        },
        "required": ["resume_data", "match_report", "reflective_questions"],
    },
}

REQUIRED_TOP_LEVEL_KEYS = ("resume_data", "match_report", "reflective_questions")


class CoachError(Exception):
    pass


def _diagnose(category: str) -> None:
    # Category only - never the resume/job-posting text or the model's
    # actual output. Safe to print; nothing sensitive ever reaches this call.
    print(f"[coach] Right Fit analysis attempt failed: {category}")


def _extract_tool_input(response) -> dict:
    """Pull the submit_analysis tool call's input out of a response.
    Raises ValueError (caught by the caller) if the tool wasn't called, was
    cut off before completing, or is missing a required top-level key."""
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == "submit_analysis"]
    if not tool_blocks:
        raise ValueError("invalid_json")  # model didn't call the tool at all

    data = tool_blocks[0].input
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def _call_model(client, messages):
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "submit_analysis"},
        messages=messages,
    )


def analyze(resume_text: str, job_posting: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CoachError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(resume_text=resume_text, job_posting=job_posting)

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = _call_model(client, [{"role": "user", "content": prompt_for_this_attempt}])
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise CoachError("We couldn't complete this analysis right now. Please try again.") from e

        log_usage("right_fit", response)
        try:
            return _extract_tool_input(response)
        except ValueError as e:
            _diagnose(str(e))

    raise CoachError("We couldn't complete this analysis right now. Please try again.")
