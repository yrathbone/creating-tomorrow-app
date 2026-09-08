"""
The "Build My Resume" tool: takes ONLY an old resume (no job posting
required) and uses live web search to research what the person's current
or most recent role typically requires industry-wide today, then produces
reflective yes/no questions the same way the comparison tool does - but
grounded in general role research instead of one specific posting.

This is for someone who wants a better, honest resume before they've even
found a job to apply to.
"""
import json
import os

import anthropic

from llm_utils import extract_final_text, extract_json_object

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")
MAX_SEARCHES = int(os.environ.get("CT_MAX_SEARCHES", "5"))

SYSTEM_PROMPT = """You are Nova, a career coach helping a job seeker \
honestly rebuild their resume. You are given raw text extracted from \
someone's OLD resume (it may be in any order or layout - it's just \
extracted text).

Do four things:

1. RESTRUCTURE the old resume into a clean JSON schema (below). Preserve \
all real content faithfully. Do not invent, embellish, or infer anything \
that isn't actually in the source text. If contact info is incomplete, \
leave it out rather than guessing. Keep bullet points close to their \
original wording, but you may tighten grammar/phrasing for clarity.

2. IDENTIFY the person's current or most recent job title from the resume.

3. Use the web_search tool to research what that job title typically \
requires TODAY, industry-wide - not from this person's resume, but from \
real job postings and role descriptions you find on the web. Search for \
things like "[job title] job description requirements" or "[job title] \
skills responsibilities". Look at a few real results, not just one, \
before drawing conclusions.

4. Based on that research, write 3-6 REFLECTIVE QUESTIONS a coach would \
ask to find out whether the candidate has relevant unlisted experience \
common to that role. Each question must be answerable honestly with \
yes/no. For each, specify EXACTLY what would be added to the resume if \
the answer is yes - either one new skill, or one new bullet under a \
specific existing job (reference it by its index in the "experience" \
array you produced in step 1, 0 = most recent/first listed). Never \
assume yes. Never invent experience - only ask.

After you finish researching, your FINAL message must contain ONLY a \
JSON object - no commentary, no citations, no markdown code fence, \
nothing before or after it - in this exact shape:

{
  "resume_data": {
    "name": "FULL NAME",
    "contact": "City, ST | Phone | Email | LinkedIn (omit parts not found)",
    "summary": "one paragraph, or omit if none existed in the source",
    "skills": ["skill one", "skill two"],
    "experience": [
      {"title": "Job Title", "subtitle": "Company, City, ST — Start – End", "bullets": ["...", "..."]}
    ],
    "education": ["Degree – School, City, ST"]
  },
  "role_research_summary": "2-4 plain-language sentences on what real postings for this role commonly involve today, based on what you found",
  "reflective_questions": [
    {
      "id": "q1",
      "question": "People in [role] commonly do X — did you do this?",
      "add_if_yes": {
        "type": "skill" | "bullet",
        "experience_index": 0,
        "text": "the exact skill or bullet text to add if confirmed"
      }
    }
  ]
}

("experience_index" is only meaningful when type is "bullet" - omit or \
ignore it for "skill" type.)
"""

USER_PROMPT_TEMPLATE = """OLD RESUME TEXT (raw extraction, order may be jumbled):
{resume_text}

Research this person's role and produce the analysis as specified in the system prompt."""


class BuilderError(Exception):
    pass


def build(resume_text: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise BuilderError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(resume_text=resume_text)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,  # extended thinking + search results both count against this
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}],
        )
    except anthropic.APIError as e:
        raise BuilderError(f"Claude API error: {e}") from e

    text = extract_final_text(response)
    try:
        return extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise BuilderError(f"Could not parse model response as JSON: {e}") from e
