"""
Elevate: a discovery-interview tool that surfaces experience a candidate
under-described on their own resume, then rewrites the resume to include
only what they explicitly confirmed. "Refine fixes the document. Elevate
discovers the person."

Three calls, three stages of one interview:
  analyze_for_discovery() - restructures the uploaded resume faithfully (no
                   polish yet), writes a short warm analysis of the areas
                   of experience it sees, and returns the first batch of
                   resume-specific yes/no discovery questions.
  discover()       - the repeating interview loop. Given the full growing
                   history of questions asked and answers given so far, it
                   either returns another batch of questions (broad yes/no
                   questions for unexplored areas, or a specific follow-up
                   converting a "yes" into bullet-usable detail), or - once
                   enough has been gathered, or the user asked to finish -
                   a list of candidate "discovered facts" built strictly
                   from what was actually said, for the user to confirm,
                   edit, or remove before anything is added to the resume.
  finalize_elevate() - takes the original resume facts plus the user's
                   confirmed facts and produces the final elevated resume:
                   a positioning headline, rewritten summary, merged core
                   expertise, and confirmed facts folded into the right
                   experience entries - plus a plain-language summary of
                   what was uncovered, what changed, and what to verify.

Never invents. A skill, responsibility, accomplishment, metric,
technology, leadership scope, or certification may only reach the final
resume if the candidate explicitly confirmed it during the interview.

Structured output: like coach.py (Right Fit), upgrade.py (Refine), and
profile_review.py (Spotlight), each of the three calls below is requested
via a forced tool call (tool_choice) against an explicit input_schema,
rather than asking the model to emit raw JSON text - the same fix applied
to those three tools after the same underlying failure mode (extended
thinking consuming the whole token budget on some inputs, leaving no room
for the actual output). discover() is the one exception worth understanding:
it can legitimately produce one of TWO different shapes each turn (another
batch of questions, or the discovered-facts confirmation) - handled by
offering two tools and forcing the model to call ONE of them
(tool_choice type "any", restricted to just those two), rather than one tool
with an either/or schema.
"""
import json
import os

import anthropic

from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")

# See coach.py for why this is larger than it looks like it should need to
# be: extended thinking eats a large, variable chunk of this budget before
# the actual structured output is produced.
MAX_TOKENS = 16000

ANALYZE_SYSTEM_PROMPT = """You are Nova, a thoughtful career strategist conducting a discovery interview - not a document formatter. Your job in this step is to understand the person's actual career, then figure out what to ask them about.

You are given raw text extracted from someone's existing resume (it may be in any order or layout - it's just extracted text).

Do three things:

1. RESTRUCTURE the resume faithfully into the JSON schema below. Preserve all real content - do not invent, embellish, polish, or infer anything not in the source text. This is a faithful transcription step, not a rewrite: keep the candidate's own wording for now. If contact info is incomplete, leave it out rather than guessing. Write date ranges in numeric MM/YY format, keeping "Present"/"Current" as-is.

2. Write a short, warm, conversational ANALYSIS of the career areas you see - 2-4 sentences, naming the specific functional areas, industries, or types of work the resume shows evidence of. Never say or imply the resume is "bad," weak, or lacking. Frame it as a strong starting point with more likely underneath it. Something in the spirit of: "Your resume gives me a strong starting point. I see experience in commercial banking, client relationship management, and lending operations. There may be parts of your experience that aren't fully represented yet - I'd like to ask you a few questions before rebuilding your resume."

3. Infer 2-4 CATEGORIES of experience specific to THIS resume - not a generic checklist. For example (these are illustrations only, not a fixed list - infer whatever actually fits): someone in operational risk/controls might warrant categories like RCSA participation, audit/examiner coordination, governance/committee leadership; someone in treasury/banking might warrant treasury products supported, RFP/pitch involvement, senior client contacts; someone in client service might warrant account/relationship scope, escalation handling, process improvement; someone in technology might warrant systems/platforms used, solution design, stakeholder collaboration. Generalize this idea to whatever this specific resume's field actually is.

4. For those categories, write the FIRST BATCH of 4-6 yes/no discovery questions - specific, resume-grounded questions about responsibilities, scope, or accomplishments that are common in this candidate's apparent field but that this resume doesn't currently mention. Each must be answerable honestly with yes/no. Never assume yes. Do not overwhelm - 4-6 questions is the right size for a first batch, not more.

Call the submit_discovery_start tool with the restructured resume, \
analysis, categories, and first question batch. Do not respond with plain \
text."""

ANALYZE_USER_PROMPT_TEMPLATE = """RESUME TEXT (raw extraction, order may be jumbled):
{resume_text}

Produce the restructured resume, analysis, categories, and first question batch as specified in the system prompt."""

DISCOVER_SYSTEM_PROMPT = """You are Nova, continuing a career-discovery interview. You are given the candidate's restructured resume, the categories of experience being explored, and the FULL history of every question asked so far and how they answered (type "yes_no" questions are answered yes/no/skip; type "detail" questions are answered in the candidate's own free-text words).

Your job each turn is to decide what happens next:

A) If there is more useful ground to cover, respond with stage "questions" and a new batch of 2-5 questions. Prioritize, in this order:
   1. For every "yes_no" question already answered "yes" that does NOT yet have a matching "detail" follow-up answered in the history, write ONE follow-up question with "type": "detail" and "follow_up_to" set to that question's id. Follow-ups should convert a vague "yes" into something specific enough to write an honest resume bullet from - offer a few concrete example angles in the question text itself, the way a good interviewer would (e.g. "What is your role in the RFP process? For example: drafting responses, coordinating internal partners, providing pricing, gathering technical information, creating final presentations, or something else?"). Never assume which angle applies - ask.
   2. If there are still unexplored categories (or a "yes" answer surfaced a new angle worth a category of its own), add a few more "yes_no" questions for those, id'd uniquely.
   Never ask about something already answered. Never repeat a question. IDs must be unique across the ENTIRE history you were given - look at the highest-numbered existing id and continue from there (e.g. if q1-q5 exist, start new ones at q6).
   Do not send more than 5 questions in a batch, and do not plan on more than about 3 total rounds of questioning for a typical candidate - if you've already covered the main categories with reasonable depth, move to stage "confirm" rather than continuing indefinitely.

B) If enough has been gathered - most "yes" answers have a matching detail follow-up, there's nothing more productive to ask, or "force_finish" is true (the candidate asked to stop answering questions) - respond with stage "confirm" and a list of DISCOVERED FACTS built STRICTLY from what was actually said in the history. Rules for discovered_facts:
   - Every fact must trace directly to an actual answer in the history. Never invent, extrapolate, or add anything the candidate did not say.
   - A "no" or "skip" answer produces nothing.
   - A bare "yes" with no detail answer produces nothing on its own - only write a fact once there's enough specific detail to state honestly (skip anything still too vague to turn into a truthful bullet).
   - Never promote participation into ownership. If the candidate's answer suggests they supported, assisted with, or partnered on something, write it that way - do not write "led" or "owned" unless they said that.
   - Write each fact's bullet_text the way a polished, senior resume bullet would read (strong accurate verb, no invented metrics or scope), but do not editorialize beyond what was said.
   - Category should be one of the interview's categories, or a close variant if genuinely new ground came up in a detail answer.
   - If force_finish is true and nothing usable was actually confirmed, discovered_facts may be an empty list - that's fine and honest.

Call ONE tool with your decision: submit_questions if there's more to ask, \
or submit_confirm if it's time to move to the discovered-facts \
confirmation. Do not respond with plain text, and do not call both."""

DISCOVER_USER_PROMPT_TEMPLATE = """RESTRUCTURED RESUME:
{resume_json}

INTERVIEW CATEGORIES: {categories}

FULL Q&A HISTORY SO FAR (round {round_number}):
{history_text}

FORCE FINISH: {force_finish}

Decide the next step as specified in the system prompt."""

FINALIZE_SYSTEM_PROMPT = """You are Nova, an expert executive resume writer and career strategist, finishing an Elevate discovery interview. You are given the candidate's original restructured resume facts AND a list of CONFIRMED FACTS the candidate explicitly approved during the interview - both together are the sole source of truth. Nothing else may be added.

FACTUAL SAFETY RULES (non-negotiable):
Never invent skills, technologies, employers, job titles, metrics, revenue, team sizes, certifications, education, products, responsibilities, leadership scope, client types, awards, or years of experience. Only the original resume content and the supplied confirmed facts may appear. If something is uncertain, leave it out.
Never promote participation into ownership: if source text says "supported" do not write "led"; if it says "partnered with" do not write "owned"; if it says a matter was escalated, do not claim it was personally resolved.

WRITING STYLE:
Senior, polished, confident, concise, human. Avoid repetitive AI resume language such as "results-driven," "dynamic," "dynamic professional," "highly motivated," "proven professional," "seasoned professional," "proven track record," or "hard-working" unless truly appropriate given the evidence. Prefer a specific professional identity over generic claims (e.g. "Commercial banking professional with more than a decade of experience spanning client service, treasury operations, lending documentation, and regulatory compliance" rather than "Results-driven banking professional with strong communication skills.").

CAREER NARRATIVE: if the work history (including any confirmed facts) shows a genuine progression - for example client service, then lending, then treasury sales - the summary may reflect that with language like "Progressive experience across client service, lending operations, and treasury sales." Only describe progression the dates and titles actually support. Never invent a promotion, a title change, or a narrative arc that isn't there.

Build the final resume:
1. A POSITIONING HEADLINE: 2-3 short pipe-separated capitalized phrases capturing the candidate's professional identity, supported only by confirmed experience (e.g. "OPERATIONAL RISK & CONTROLS | BUSINESS OPERATIONS | TREASURY GOVERNANCE").
2. A rewritten PROFESSIONAL SUMMARY (3-5 lines) that reflects the fuller picture now that confirmed facts are included.
3. CORE EXPERTISE: a merged, deduplicated list of skills/expertise phrases drawn from the original resume plus whatever the confirmed facts demonstrate.
4. PROFESSIONAL EXPERIENCE: rewrite each job's bullets with polished, accurate language, and fold each confirmed fact's bullet_text into the single most relevant existing job entry (matching by category, timing, or context) - never invent a new employer or role to hold it. If a confirmed fact doesn't clearly belong to one job more than another, add it to the most recent relevant role. EXCEPTION: if a confirmed fact makes clear that what was one combined entry is actually two distinct roles (e.g. a different title started partway through a date range that was previously listed as a single continuous position), split it into two separate experience entries with corrected date ranges - this is using the candidate's own confirmed words to fix an inaccuracy, not inventing a new employer or role. Any time you split, merge, or otherwise restructure an existing entry this way, add a specific "verify" item naming exactly what was restructured (e.g. "We split your JPMorgan Chase entry into two roles based on what you confirmed - double check both date ranges") - don't just fold the change in silently.
5. EDUCATION and CERTIFICATIONS: pass through unchanged from the original resume (certifications only if the original resume actually listed any - otherwise omit).

Then write the FINAL ELEVATE SUMMARY:
- "uncovered": one bullet per confirmed fact that was newly added, in plain language (what was uncovered).
- "changes": plain-language list of what changed in the rewrite (e.g. "Strengthened professional positioning", "Reformatted for ATS readability", and - only if confirmed facts exist - "Added confirmed experience that was missing").
- "verify": a short reminder list of things the candidate should double check - always include employment dates, job titles, and contact information; also include any metrics, a specific item for any entry you split/merged/restructured (see above), and, if any confirmed facts were added, "newly confirmed experience" as an item.

Call the submit_final_resume tool with the final elevated resume and \
summary. Do not respond with plain text."""

FINALIZE_USER_PROMPT_TEMPLATE = """ORIGINAL RESTRUCTURED RESUME:
{resume_json}

CONFIRMED FACTS (approved by the candidate - the only new content allowed):
{facts_text}

Produce the final elevated resume and summary as specified in the system prompt."""


RETRY_NOTE = """

(Note: a prior attempt at this same request did not come back as a \
complete, valid tool call. Please produce the full result again as one \
complete tool call.)"""

_RESUME_DATA_PROPS = {
    "name": {"type": "string"},
    "contact": {"type": "string"},
    "summary": {"type": "string"},
    "skills": {"type": "array", "items": {"type": "string"}},
    "experience": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "bullets": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "subtitle", "bullets"],
        },
    },
    "education": {"type": "array", "items": {"type": "string"}},
}

ANALYZE_TOOL = {
    "name": "submit_discovery_start",
    "description": "Submit the restructured resume, analysis, categories, and first question batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_data": {
                "type": "object",
                "properties": _RESUME_DATA_PROPS,
                "required": ["name", "contact", "skills", "experience", "education"],
            },
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
        "required": ["resume_data", "analysis_summary", "categories", "questions"],
    },
}

DISCOVER_QUESTIONS_TOOL = {
    "name": "submit_questions",
    "description": "Submit the next batch of discovery questions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string"},
                        "question": {"type": "string"},
                        "type": {"type": "string", "enum": ["yes_no", "detail"]},
                        "follow_up_to": {"type": ["string", "null"]},
                    },
                    "required": ["id", "category", "question", "type", "follow_up_to"],
                },
            },
        },
        "required": ["questions"],
    },
}

DISCOVER_CONFIRM_TOOL = {
    "name": "submit_confirm",
    "description": "Submit the discovered facts for the candidate to confirm, once the interview has gathered enough.",
    "input_schema": {
        "type": "object",
        "properties": {
            "discovered_facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string"},
                        "bullet_text": {"type": "string"},
                    },
                    "required": ["id", "category", "bullet_text"],
                },
            },
        },
        "required": ["discovered_facts"],
    },
}

FINALIZE_TOOL = {
    "name": "submit_final_resume",
    "description": "Submit the final elevated resume and summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_data": {
                "type": "object",
                "properties": {
                    **_RESUME_DATA_PROPS,
                    "headline": {"type": "string"},
                    "certifications": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "contact", "headline", "summary", "skills", "experience", "education"],
            },
            "uncovered": {"type": "array", "items": {"type": "string"}},
            "changes": {"type": "array", "items": {"type": "string"}},
            "verify": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["resume_data", "uncovered", "changes", "verify"],
    },
}


class ElevateError(Exception):
    pass


def _diagnose(category: str) -> None:
    print(f"[elevate] Elevate attempt failed: {category}")


def _extract_tool_input(response, tool_name: str, required_keys: tuple) -> dict:
    """For calls where exactly one specific tool must be called."""
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


def _extract_discover_input(response) -> dict:
    """discover() can legitimately call EITHER submit_questions or
    submit_confirm - whichever the model decides is appropriate this turn.
    Returns the same {"stage": ..., ...} shape the frontend already expects,
    regardless of which tool was actually called."""
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
    if not tool_blocks:
        raise ValueError("invalid_json")

    block = tool_blocks[0]
    if block.name == "submit_questions":
        if "questions" not in block.input:
            raise ValueError("missing_required_field")
        return {"stage": "questions", "questions": block.input["questions"]}
    elif block.name == "submit_confirm":
        if "discovered_facts" not in block.input:
            raise ValueError("missing_required_field")
        return {"stage": "confirm", "discovered_facts": block.input["discovered_facts"]}
    else:
        raise ValueError("invalid_json")  # neither expected tool was called


def _call_with_retry(label: str, system_prompt: str, user_prompt: str, tools: list, tool_choice: dict, extract) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ElevateError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()

    for attempt in range(2):  # original attempt + at most one retry
        prompt_for_this_attempt = user_prompt + (RETRY_NOTE if attempt > 0 else "")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                tools=tools,
                tool_choice=tool_choice,
                messages=[{"role": "user", "content": prompt_for_this_attempt}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise ElevateError("We couldn't complete this step right now. Please try again.") from e

        log_usage(label, response)
        try:
            return extract(response)
        except ValueError as e:
            _diagnose(str(e))

    raise ElevateError("We couldn't complete this step right now. Please try again.")


def analyze_for_discovery(resume_text: str) -> dict:
    user_prompt = ANALYZE_USER_PROMPT_TEMPLATE.format(resume_text=resume_text)
    return _call_with_retry(
        "elevate_start",
        ANALYZE_SYSTEM_PROMPT,
        user_prompt,
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "tool", "name": "submit_discovery_start"},
        extract=lambda r: _extract_tool_input(
            r, "submit_discovery_start", ("resume_data", "analysis_summary", "categories", "questions")
        ),
    )


def _format_history(history: list) -> str:
    if not history:
        return "(no questions answered yet)"
    lines = []
    for h in history:
        follow = f" (follow-up to {h['follow_up_to']})" if h.get("follow_up_to") else ""
        lines.append(
            f"- [{h.get('id')}] ({h.get('category', '')}, {h.get('type', 'yes_no')}{follow}) "
            f"Q: {h.get('question')}\n  A: {h.get('answer')}"
        )
    return "\n".join(lines)


def discover(resume_data: dict, categories: list, history: list, force_finish: bool, round_number: int = 1) -> dict:
    user_prompt = DISCOVER_USER_PROMPT_TEMPLATE.format(
        resume_json=json.dumps(resume_data, indent=2),
        categories=", ".join(categories) if categories else "(none identified)",
        round_number=round_number,
        history_text=_format_history(history),
        force_finish="true" if force_finish else "false",
    )
    return _call_with_retry(
        "elevate_discover",
        DISCOVER_SYSTEM_PROMPT,
        user_prompt,
        tools=[DISCOVER_QUESTIONS_TOOL, DISCOVER_CONFIRM_TOOL],
        tool_choice={"type": "any"},
        extract=_extract_discover_input,
    )


def finalize_elevate(resume_data: dict, confirmed_facts: list) -> dict:
    facts_text = (
        "\n".join(f"- ({f.get('category', '')}) {f.get('bullet_text', '')}" for f in confirmed_facts)
        if confirmed_facts
        else "(none confirmed - the candidate didn't confirm any new facts, only polish the original content)"
    )
    user_prompt = FINALIZE_USER_PROMPT_TEMPLATE.format(
        resume_json=json.dumps(resume_data, indent=2),
        facts_text=facts_text,
    )
    return _call_with_retry(
        "elevate_finalize",
        FINALIZE_SYSTEM_PROMPT,
        user_prompt,
        tools=[FINALIZE_TOOL],
        tool_choice={"type": "tool", "name": "submit_final_resume"},
        extract=lambda r: _extract_tool_input(r, "submit_final_resume", ("resume_data", "uncovered", "changes", "verify")),
    )
