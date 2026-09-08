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
"""
import json
import os

import anthropic

from llm_utils import extract_final_text, extract_json_object

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")
MAX_SEARCHES = int(os.environ.get("CT_SCRATCH_MAX_SEARCHES", "3"))

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
it's fine to produce just 1-2 bullets. Never pad with invented detail.

2. Use the web_search tool to research what this type of role commonly \
involves today (search real job postings or role descriptions for this \
title). Based on that, write 2-3 REFLECTIVE QUESTIONS about commonly-\
related responsibilities they didn't mention, each answerable honestly \
with yes/no. Never assume yes. Only ask.

After you finish researching, your FINAL message must contain ONLY a \
JSON object - no commentary, no citations, no markdown code fence - in \
this exact shape:

{
  "drafted_bullets": ["bullet one", "bullet two"],
  "reflective_questions": [
    {"id": "q1", "question": "People in this kind of role often do X — did you?", "bullet_if_yes": "the exact bullet text to add if they confirm"}
  ]
}
"""

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

Respond ONLY with a JSON object, no other text:

{
  "suggested_summary": "...",
  "suggested_skills": ["skill one", "skill two"]
}
"""

FINALIZE_USER_PROMPT_TEMPLATE = """NAME: {name}

EXPERIENCE:
{experience_text}

EDUCATION:
{education_text}

SKILLS THEY ALREADY LISTED THEMSELVES:
{existing_skills}

Produce the summary and skill suggestions as specified in the system prompt."""


class ScratchError(Exception):
    pass


def _call(system_prompt: str, user_prompt: str, use_search: bool) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ScratchError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    kwargs = dict(
        model=MODEL,
        max_tokens=6000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if use_search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}]

    try:
        response = client.messages.create(**kwargs)
    except anthropic.APIError as e:
        raise ScratchError(f"Claude API error: {e}") from e

    text = extract_final_text(response)
    try:
        return extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise ScratchError(f"Could not parse model response as JSON: {e}") from e


def draft_entry(entry_type: str, title: str, organization: str, dates: str, description: str) -> dict:
    user_prompt = ENTRY_USER_PROMPT_TEMPLATE.format(
        entry_type=entry_type,
        title=title,
        organization=organization,
        dates=dates,
        description=description,
    )
    return _call(ENTRY_SYSTEM_PROMPT, user_prompt, use_search=True)


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
    return _call(FINALIZE_SYSTEM_PROMPT, user_prompt, use_search=False)
