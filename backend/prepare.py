"""
Prepare: an interview-preparation tool. Takes a target job description and
(optionally) the text of a candidate's resume, and produces the themes the
employer likely cares about, a set of grouped interview questions with a
plain-language reason for each one, and a few thoughtful questions the
candidate could ask the interviewer.

Same shape as coach.py: one Claude call, one structured response.
"We don't invent your value. We help you see it." - so this never invents
resume content, never predicts whether the candidate will get the job, and
always hedges with "likely"/"may"/"could" rather than claiming certainty
about what a real interviewer will ask.

Structured output: like coach.py (Right Fit), upgrade.py (Refine), and
profile_review.py (Spotlight), the result is requested via a forced tool
call (tool_choice) against an explicit input_schema, rather than asking the
model to emit raw JSON text - the same fix applied to those three tools
after the same underlying failure mode (extended thinking consuming the
whole token budget on some inputs, leaving no room for the actual output).
"""
import os

import anthropic

from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")

# See coach.py for why this is larger than it looks like it should need to
# be: extended thinking eats a large, variable chunk of this budget before
# the actual structured output is produced.
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are Nova, a thoughtful career coach helping a job \
seeker prepare for a real interview. You are given the text of a JOB \
DESCRIPTION they want to interview for, and OPTIONALLY the text of their \
RESUME (it may be absent - not every candidate provides one).

Your guiding philosophy: "We don't invent your value. We help you see \
it." Help this person recognize what they already bring, using their own \
real background - never invent experience, and never fabricate anything \
about the employer that isn't actually implied by the posting.

Do four things:

1. EMPLOYER PRIORITIES: identify 4-6 concise themes this employer \
appears to care about, based strictly on language actually in the job \
description (responsibilities, required/preferred qualifications, tone). \
Do not guess at priorities the posting doesn't actually support. Keep \
each theme to a short phrase (e.g. "Stakeholder management", "Regulatory \
knowledge").

2. INTERVIEW QUESTIONS: write 10-15 realistic interview questions, \
organized into groups. Use these possible group categories, in this \
order, and OMIT any group that doesn't apply (do not include a group \
with zero questions):
   - "Behavioral Questions": about prior experience, judgment, \
communication, conflict, leadership, collaboration, problem solving.
   - "Role-Specific Questions": grounded directly in this posting's \
stated responsibilities and requirements.
   - "Technical or Industry Questions": ONLY include this group if the \
posting actually signals that technical or industry-specific knowledge \
matters for this role.
   - "Resume-Based Questions": ONLY include this group if a resume was \
actually provided. Every question here must be about something \
genuinely present in the resume text - never assume a skill, employer, \
accomplishment, or qualification that isn't actually written there.

For EACH question, provide:
   - "question": the interview question itself.
   - "why": a short, concise, user-facing explanation of why an \
interviewer may ask this. Never expose internal reasoning or chain of \
thought - just the plain observation a helpful coach would say out loud.
   - "source": "job_description" if the question is grounded in \
specific posting language, "resume" if it's grounded in the candidate's \
own resume content, or "general" if it's a standard question for this \
type of role not tied to one specific phrase.
   - "signal": when source is "job_description", a short quote or close \
paraphrase from the posting that prompted this question. When source is \
"resume", a short quote or close paraphrase from the resume. When source \
is "general", use null.

Use hedged language throughout ("likely", "may", "could") - never claim \
these are the exact questions the employer will ask. Never write a \
question touching age, race, religion, disability, pregnancy, marital \
status, national origin, sexual orientation, citizenship, or other \
protected characteristics. Never state or imply whether this candidate \
is qualified or unqualified for the role.

3. CANDIDATE QUESTIONS: write about 5 thoughtful questions this \
candidate could ask the interviewer, each specific to details actually \
in this job description - not generic questions like "what's the \
culture like" when something more specific can be built from the \
posting's own language (e.g. a specific team, partnership, metric, or \
responsibility it mentions).

4. PREP TIP: one short, encouraging reminder (1-3 sentences) that the \
candidate doesn't need memorized perfect answers - just real examples \
from experience they already have that demonstrate what this role \
appears to value.

Call the submit_prep tool with your complete result. Do not respond with \
plain text."""

USER_PROMPT_TEMPLATE = """JOB DESCRIPTION:
{job_description}

RESUME TEXT:
{resume_text}

Produce the employer priorities, grouped interview questions, candidate \
questions, and prep tip as specified in the system prompt."""

NO_RESUME_PLACEHOLDER = "(no resume was provided - omit the \"Resume-Based Questions\" group entirely)"

RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid submit_prep call. Please produce the full result again as \
one complete submit_prep tool call.)"""

PREPARE_TOOL = {
    "name": "submit_prep",
    "description": "Submit the completed interview-prep result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "employer_priorities": {"type": "array", "items": {"type": "string"}},
            "question_groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "Behavioral Questions",
                                "Role-Specific Questions",
                                "Technical or Industry Questions",
                                "Resume-Based Questions",
                            ],
                        },
                        "questions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "question": {"type": "string"},
                                    "why": {"type": "string"},
                                    "source": {"type": "string", "enum": ["job_description", "resume", "general"]},
                                    "signal": {"type": ["string", "null"]},
                                },
                                "required": ["id", "question", "why", "source", "signal"],
                            },
                        },
                    },
                    "required": ["category", "questions"],
                },
            },
            "candidate_questions": {"type": "array", "items": {"type": "string"}},
            "prep_tip": {"type": "string"},
        },
        "required": ["employer_priorities", "question_groups", "candidate_questions", "prep_tip"],
    },
}

REQUIRED_TOP_LEVEL_KEYS = ("employer_priorities", "question_groups", "candidate_questions", "prep_tip")


class PrepareError(Exception):
    pass


def _diagnose(category: str) -> None:
    print(f"[prepare] Prepare attempt failed: {category}")


def _extract_tool_input(response) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == "submit_prep"]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def prepare(job_description: str, resume_text: str = "") -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise PrepareError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        job_description=job_description,
        resume_text=resume_text.strip() if resume_text.strip() else NO_RESUME_PLACEHOLDER,
    )

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[PREPARE_TOOL],
                tool_choice={"type": "tool", "name": "submit_prep"},
                messages=[{"role": "user", "content": prompt_for_this_attempt}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise PrepareError("We couldn't prepare your interview prep right now. Please try again.") from e

        log_usage("prepare", response)
        try:
            return _extract_tool_input(response)
        except ValueError as e:
            _diagnose(str(e))

    raise PrepareError("We couldn't prepare your interview prep right now. Please try again.")
