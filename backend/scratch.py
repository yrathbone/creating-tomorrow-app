"""
The "Start From Scratch" tool: helps someone with NO existing resume build
one from zero, one experience entry at a time. Aimed at first-time resume
builders (teens, people entering the workforce for the first time) - plain
language, encouraging, never condescending.

Two calls:
  draft_entry()  - one job/volunteer/school-activity entry at a time: turns
                   their own plain description into resume bullets (strictly
                   grounded in what they said), plus researches the role live
                   to ask a few honest reflective questions.
  finalize()     - once all entries are in, drafts a summary paragraph and
                   suggests a few likely skills based on the whole picture.

Structured output: like coach.py (Right Fit) and the other tools fixed
after it, both calls here are requested via a forced tool call
(tool_choice) against an explicit input_schema, rather than asking the
model to emit raw JSON text - the same fix applied after the same
underlying failure mode (extended thinking consuming the whole token
budget on some inputs, leaving no room for the actual output).
finalize() uses the same tool_choice="tool" pattern as coach.py. draft_entry()
is the one call in this app that ALSO needs Claude's server-side web_search
tool, which can't be combined with tool_choice forcing a single specific
tool (the model would never be allowed to call web_search first). The fix
used here instead is tool_choice={"type": "any"} with BOTH web_search and
the custom submit_draft tool available - "any" only requires the model to
call *some* tool rather than respond with plain text, so it's free to
search first and call submit_draft once it's done. Empirically verified
(5/5 test calls) that the model reliably searches first, then submits.
"""
import os

import anthropic

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")
MAX_SEARCHES = int(os.environ.get("CT_SCRATCH_MAX_SEARCHES", "3"))

# See coach.py for why this is larger than it looks like it should need to
# be: extended thinking eats a large, variable chunk of this budget before
# the actual structured output is produced.
DRAFT_MAX_TOKENS = 8000
FINALIZE_MAX_TOKENS = 16000

ENTRY_SYSTEM_PROMPT = """You are Nova, helping someone build their very \
first resume from scratch. This person likely has little or no resume-\
writing experience - possibly a teen or someone entering the workforce \
for the first time. Be warm, plain-spoken, and encouraging. Never sound \
corporate or condescending.

You're given basic facts about ONE role they had (a job, a volunteer \
position, or a school activity/club) and, in their own words, what they \
did there.

Do two things:

1. Turn their own description into 2-4 clear, resume-style bullet \
points. Stay strictly grounded in what they actually said - rephrase and \
structure it professionally, but do not add tasks, outcomes, numbers, or \
skills they did not mention. If they only gave you one short sentence, \
it's fine to produce just 1 bullet - never pad with invented detail, and \
never pad by turning the role/organization/dates itself into a bullet \
(e.g. "Worked as a server at X for four years") - that information is \
already shown in the resume's own title/company/dates line directly \
above the bullets, so restating it is redundant. Every bullet must \
describe an actual activity, responsibility, or task.

2. Use the web_search tool to research what this type of role commonly \
involves today (search real job postings or role descriptions for this \
title). Based on that, write 2-3 REFLECTIVE QUESTIONS about commonly-\
related responsibilities they didn't mention, each answerable honestly \
with yes/no. Never assume yes. Only ask.

After you finish researching, call the submit_draft tool with your \
drafted bullets and reflective questions. Do not respond with plain text."""

ENTRY_USER_PROMPT_TEMPLATE = """ENTRY TYPE: {entry_type}
ROLE / TITLE: {title}
ORGANIZATION: {organization}
DATES: {dates}

WHAT THEY SAID THEY DID (in their own words):
{description}

Produce the analysis as specified in the system prompt."""

FINALIZE_SYSTEM_PROMPT = """You are Nova, helping someone finish building \
their very first resume. You're given their name, every experience entry \
they've built so far (with finalized bullets), their education, and any \
skills they typed in themselves.

Do two things:

1. Draft a warm, honest 2-3 sentence PROFESSIONAL SUMMARY based only on \
what's actually in their experience and education. Do not invent \
achievements, years of experience, or skills not evidenced by what's \
there. If their experience is limited (e.g. one part-time job or school \
activities only), write a summary that's honest about that while still \
sounding confident about what they do bring.

2. Suggest 4-8 additional SKILLS that reasonably follow from their listed \
experience (e.g. someone who worked retail plausibly has "Customer \
Service" and "Cash Handling" skills) but that they haven't explicitly \
listed yet. These are suggestions for them to confirm, not facts - don't \
suggest anything not clearly implied by what they described.

Call the submit_finalize tool with the summary and suggested skills. Do \
not respond with plain text."""

FINALIZE_USER_PROMPT_TEMPLATE = """NAME: {name}

EXPERIENCE:
{experience_text}

EDUCATION:
{education_text}

SKILLS THEY ALREADY LISTED THEMSELVES:
{existing_skills}

Produce the summary and skill suggestions as specified in the system prompt."""


RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid tool call. Please produce the full result again as one \
complete tool call.)"""

DRAFT_TOOL = {
    "name": "submit_draft",
    "description": "Submit the drafted resume bullets and reflective questions for this one entry.",
    "input_schema": {
        "type": "object",
        "properties": {
            "drafted_bullets": {"type": "array", "items": {"type": "string"}},
            "reflective_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "question": {"type": "string"},
                        "bullet_if_yes": {"type": "string"},
                    },
                    "required": ["id", "question", "bullet_if_yes"],
                },
            },
        },
        "required": ["drafted_bullets", "reflective_questions"],
    },
}

FINALIZE_TOOL = {
    "name": "submit_finalize",
    "description": "Submit the suggested professional summary and additional skills.",
    "input_schema": {
        "type": "object",
        "properties": {
            "suggested_summary": {"type": "string"},
            "suggested_skills": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["suggested_summary", "suggested_skills"],
    },
}

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}


class ScratchError(Exception):
    pass


def _diagnose(category: str) -> None:
    print(f"[scratch] Beginning attempt failed: {category}")


def _extract_tool_input(response, tool_name: str, required_keys: tuple) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == tool_name]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def _call_with_retry(system_prompt: str, user_prompt: str, tools: list, tool_choice: dict, max_tokens: int, extract) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ScratchError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                messages=[{"role": "user", "content": prompt_for_this_attempt}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise ScratchError("We couldn't complete this right now. Please try again.") from e

        try:
            return extract(response)
        except ValueError as e:
            _diagnose(str(e))

    raise ScratchError("We couldn't complete this right now. Please try again.")


def draft_entry(entry_type: str, title: str, organization: str, dates: str, description: str) -> dict:
    user_prompt = ENTRY_USER_PROMPT_TEMPLATE.format(
        entry_type=entry_type,
        title=title,
        organization=organization,
        dates=dates,
        description=description,
    )
    # tool_choice can't be forced to one specific tool here, since the model
    # also needs the freedom to call web_search (possibly more than once)
    # before it's ready to submit - "any" requires it to call SOME tool
    # rather than respond with plain text, without pinning down which one
    # first. See the module docstring for why this differs from every other
    # tool in the app, and the empirical verification behind it.
    return _call_with_retry(
        ENTRY_SYSTEM_PROMPT,
        user_prompt,
        tools=[WEB_SEARCH_TOOL, DRAFT_TOOL],
        tool_choice={"type": "any"},
        max_tokens=DRAFT_MAX_TOKENS,
        extract=lambda r: _extract_tool_input(r, "submit_draft", ("drafted_bullets", "reflective_questions")),
    )


def finalize(name: str, experience: list, education: list, existing_skills: list) -> dict:
    experience_text = "\n\n".join(
        f"{e['title']} — {e['subtitle']}\n" + "\n".join(f"- {b}" for b in e["bullets"])
        for e in experience
    ) or "(none yet)"
    education_text = "\n".join(f"- {line}" for line in education) or "(none yet)"
    existing_skills_text = ", ".join(existing_skills) if existing_skills else "(none listed)"

    user_prompt = FINALIZE_USER_PROMPT_TEMPLATE.format(
        name=name,
        experience_text=experience_text,
        education_text=education_text,
        existing_skills=existing_skills_text,
    )
    return _call_with_retry(
        FINALIZE_SYSTEM_PROMPT,
        user_prompt,
        tools=[FINALIZE_TOOL],
        tool_choice={"type": "tool", "name": "submit_finalize"},
        max_tokens=FINALIZE_MAX_TOKENS,
        extract=lambda r: _extract_tool_input(r, "submit_finalize", ("suggested_summary", "suggested_skills")),
    )
