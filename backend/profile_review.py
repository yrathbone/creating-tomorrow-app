"""
Spotlight - reviews a LinkedIn profile using only what the person chooses
to share: screenshots, pasted text, and/or a PDF export, in any
combination. No LinkedIn scraping, login, or API of any kind - this only
ever sees what was uploaded/pasted in this one request. A resume upload is
also optional - when supplied, it's additional context (not a separate
thing to review) used only to add real, already-documented detail to the
LinkedIn profile's own existing roles - see SAMPLE UPDATED PROFILE below.

One call: review_profile() sends everything supplied (images + text) to
Claude in a single multi-modal message and gets back a structured review -
five sections (first impression, headline, about, experience, skills) plus
a signature "strengths with evidence" section and an optional consolidated
sample of an updated profile. No score of any kind.

Same non-fabrication discipline as every other tool here, but stricter in
one way: unlike Elevate, there's no interview to confirm anything - so if a
section wasn't actually supplied (no headline text and no screenshot showing
one, say), the model must say so plainly rather than inventing content to
fill the section.

Structured output: like coach.py (Right Fit), the review is requested via a
forced tool call (tool_choice) against an explicit input_schema, rather than
asking the model to emit raw JSON text. Diagnosed directly against this
file: with the previous free-text-JSON approach, the model's own extended
thinking was consuming the entire 8000-token budget on some real inputs,
leaving zero room for the actual JSON output and producing an unparseable
response - the same failure mode found and fixed in Right Fit. Tool-forced
output plus a larger token budget fixes it here the same way.
"""
import os

import anthropic

from llm_utils import log_usage

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")

# See coach.py for why this is larger than it looks like it should need to
# be: extended thinking eats a large, variable chunk of this budget before
# the actual structured output is produced, and this response shape (five
# sections, strengths, and now the sample updated profile) is one of the
# larger ones in the app.
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are Nova, reviewing someone's LinkedIn profile information on behalf of Creating Tomorrow, an organization whose core belief is: "We don't invent your value. We help you see it."

You are given whatever the person chose to share - some combination of: screenshots of their LinkedIn profile (read the text directly from the images), pasted profile text (possibly split into headline/about/experience/skills/additional, or pasted as one block), and text extracted from a PDF export of their profile. Not everything will always be present - work with what you actually have.

They may also optionally share the text of their resume as additional context. The resume is never reviewed on its own or treated as a separate subject - its only purpose is to give you real, already-documented detail you can draw on when strengthening the LinkedIn profile's existing roles (see SAMPLE UPDATED PROFILE below). Information from the resume is not an invention just because it isn't on LinkedIn yet - it's the person's own documented experience.

YOUR PURPOSE
Help this person understand how their profile currently communicates their real experience. Recognize existing skills, identify strengths that are actually supported by evidence, identify places that could be clearer, explain WHY a change would help, and suggest improved language they can choose to use. Teach them a little about how LinkedIn profiles work along the way. You are not writing a more impressive fictional person - you are helping a real person see their real value more clearly.

ABSOLUTE RULES - NEVER:
- Invent experience, credentials, education, accomplishments, job titles, employers, or skills not evidenced in the LinkedIn profile or the optional resume, if one was supplied.
- Invent or estimate a metric that wasn't given. If the profile says "improved onboarding," do not turn it into "reduced onboarding time by 35%" unless a 35% (or any number) was actually supplied. Preserve vague language as vague rather than inventing precision.
- Claim the person is "qualified" for anything, guarantee employment, interviews, or recruiter attention, or imply Creating Tomorrow can predict hiring outcomes.
- Produce any kind of score, rating, percentage, or red/yellow/green employability judgment. This tool teaches and explains; it does not grade or rank a person.
- Fabricate evidence to pad out a section. If there isn't enough material for something, say so honestly instead.

GUIDE'S VOICE
Everything you write should sound like Guide: calm, encouraging, curious, clear, intelligent, nonjudgmental, practical. Examples of the right tone: "I found something you may not have noticed." "There's useful experience here. It may simply need to be easier to see." "This part is strong. Here's why." "I don't have enough information to support that yet." Never sound like: "Your profile is AMAZING!", "You are definitely qualified!", "This will get recruiters' attention!", or anything with a score attached.

WHEN SOMETHING WASN'T SUPPLIED
If no headline was given (no text and no screenshot showing one), or no About text, etc., do not invent one to review. Instead set that section's "supplied" field to false and write a short, honest "note" explaining what's missing and how they could add it (e.g. "I don't have your headline yet - paste it or include a screenshot that shows it, and I'll take a look."). Leave the other fields for that section as empty lists / null.

WRITING SUGGESTED TEXT (headline, About revision, experience improvements)
Suggested language must remain fully supported by what the person actually described - do not add skills, scope, or seniority "because it sounds desirable" or "because someone in this role usually also does X." Suggested writing should sound human, avoid empty buzzwords (e.g. "results-driven," "passionate," "dynamic"), and preserve the person's real voice where it already comes through, while communicating their actual value clearly.

SKILLS & DISCOVERABILITY
Sort skills into three groups: skills CLEARLY demonstrated by specific things they described; skills that are POSSIBLE to consider only when there is real supporting evidence (not just plausible for the role); and things that NEED MORE INFORMATION before any skill claim could be made confidently. Clear terminology can help people find a profile, but never suggest keyword-stuffing.

SIGNATURE STRENGTHS SECTION
Surface 5-8 meaningful professional strengths when there's enough material - fewer is fine and expected when there isn't. EVERY strength must include a specific evidence line quoting or closely paraphrasing something the person actually described. Never write unsupported praise like "You're an exceptional leader" - show the evidence and let them recognize the strength themselves.

SAMPLE UPDATED PROFILE
If there's enough material - from the LinkedIn profile alone, or strengthened by an optional resume - produce ONE consolidated sample of what an updated profile could look like: a suggested headline, a suggested About paragraph, and for each role ALREADY LISTED on the LinkedIn profile, 2-4 suggested bullet points describing what that role actually involved.
- When a resume is supplied and describes a role that matches one already on the LinkedIn profile (by title, employer, or dates), you may pull specific, real detail from the resume into that role's suggested bullets - this is using the candidate's own words from a different document they gave you, not invention. If a LinkedIn role's title doesn't exactly match any resume title, use your judgment on overlapping dates/employer to decide if they're the same role - if it's genuinely ambiguous, it's fine to leave that role's bullets based on the LinkedIn profile alone rather than guessing which resume role it corresponds to.
- Do NOT add a role to this sample that isn't already listed somewhere on the LinkedIn profile, even if the resume mentions other past roles. Spotlight strengthens the profile the person chose to present, it does not rebuild it from scratch or add entirely new sections/roles.
- If there truly isn't enough material anywhere (no meaningful headline, About, or experience content), omit the sample profile entirely rather than producing something thin or invented.

Call the submit_review tool with your complete review. Do not respond with plain text."""

USER_PROMPT_INTRO = """Here is the profile information this person chose to share. Review it as specified in the system prompt."""

RETRY_NOTE = """

(Note: a prior attempt at this same review did not come back as a complete, \
valid submit_review call. Please produce the full review again as one \
complete submit_review tool call.)"""

_SUGGESTIONS_LIST = {"type": "array", "items": {"type": "string"}}

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the completed LinkedIn profile review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "insufficient_information": {"type": "boolean"},
            "insufficient_information_message": {"type": ["string", "null"]},
            "first_impression": {
                "type": "object",
                "properties": {
                    "whats_working": _SUGGESTIONS_LIST,
                    "could_be_clearer": _SUGGESTIONS_LIST,
                    "why_it_matters": {"type": "string"},
                },
                "required": ["whats_working", "could_be_clearer", "why_it_matters"],
            },
            "headline": {
                "type": "object",
                "properties": {
                    "supplied": {"type": "boolean"},
                    "current": {"type": ["string", "null"]},
                    "whats_working": _SUGGESTIONS_LIST,
                    "could_be_clearer": _SUGGESTIONS_LIST,
                    "suggested": {"type": ["string", "null"]},
                    "why": {"type": "string"},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["supplied", "whats_working", "could_be_clearer", "why"],
            },
            "about": {
                "type": "object",
                "properties": {
                    "supplied": {"type": "boolean"},
                    "whats_working": _SUGGESTIONS_LIST,
                    "could_be_clearer": _SUGGESTIONS_LIST,
                    "suggested_revision": {"type": ["string", "null"]},
                    "why": {"type": "string"},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["supplied", "whats_working", "could_be_clearer", "why"],
            },
            "experience": {
                "type": "object",
                "properties": {
                    "supplied": {"type": "boolean"},
                    "whats_working": _SUGGESTIONS_LIST,
                    "may_be_getting_lost": _SUGGESTIONS_LIST,
                    "suggested_improvements": _SUGGESTIONS_LIST,
                    "why": {"type": "string"},
                    "note": {"type": ["string", "null"]},
                },
                "required": ["supplied", "whats_working", "may_be_getting_lost", "suggested_improvements", "why"],
            },
            "skills": {
                "type": "object",
                "properties": {
                    "clearly_demonstrated": _SUGGESTIONS_LIST,
                    "possible_to_consider": _SUGGESTIONS_LIST,
                    "needs_more_information": _SUGGESTIONS_LIST,
                },
                "required": ["clearly_demonstrated", "possible_to_consider", "needs_more_information"],
            },
            "strengths": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["title", "evidence"],
                },
            },
            "suggested_full_profile": {
                "type": ["object", "null"],
                "properties": {
                    "headline": {"type": ["string", "null"]},
                    "about": {"type": ["string", "null"]},
                    "experience": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "organization": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "bullets"],
                        },
                    },
                },
            },
        },
        "required": ["insufficient_information", "first_impression", "headline", "about", "experience", "skills", "strengths"],
    },
}

REQUIRED_TOP_LEVEL_KEYS = ("insufficient_information", "first_impression", "headline", "about", "experience", "skills", "strengths")


class ProfileReviewError(Exception):
    pass


def _diagnose(category: str) -> None:
    # Category only - never the profile/resume text or the model's actual
    # output. Safe to print; nothing sensitive ever reaches this call.
    print(f"[profile_review] Spotlight review attempt failed: {category}")


def _extract_tool_input(response) -> dict:
    if response.stop_reason == "max_tokens":
        raise ValueError("truncated_response")

    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == "submit_review"]
    if not tool_blocks:
        raise ValueError("invalid_json")

    data = tool_blocks[0].input
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in data]
    if missing:
        raise ValueError("missing_required_field")

    return data


def review_profile(images: list, pasted_text: str, pdf_text: str, resume_text: str = "") -> dict:
    """images: list of {"media_type": "image/png"|"image/jpeg"|"image/webp", "data": <base64 str>}
    pasted_text: the combined pasted profile text (already assembled by main.py
                 from whichever fields were filled in), or "" if none.
    pdf_text: text extracted from the profile PDF via extractor.extract_text(),
              or "" if no PDF was uploaded.
    resume_text: text extracted from an optional resume upload via
                 extractor.extract_text(), or "" if none was given. Additional
                 context only - see SAMPLE UPDATED PROFILE in the system prompt.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProfileReviewError("ANTHROPIC_API_KEY is not set on the server.")

    content = [{"type": "text", "text": USER_PROMPT_INTRO}]

    if pasted_text.strip():
        content.append({"type": "text", "text": f"PASTED PROFILE TEXT:\n{pasted_text.strip()}"})

    if pdf_text.strip():
        content.append({"type": "text", "text": f"TEXT EXTRACTED FROM UPLOADED PROFILE PDF:\n{pdf_text.strip()}"})

    if resume_text.strip():
        content.append({
            "type": "text",
            "text": f"OPTIONAL RESUME TEXT (additional context only - see SAMPLE UPDATED PROFILE instructions):\n{resume_text.strip()}",
        })

    for img in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
        })

    if len(content) == 1:
        # Nothing but the intro line was added - no text, no PDF, no images.
        raise ProfileReviewError("No profile information was provided.")

    client = anthropic.Anthropic()

    for attempt in range(2):  # original attempt + at most one retry
        attempt_content = content if attempt == 0 else content + [{"type": "text", "text": RETRY_NOTE}]
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[REVIEW_TOOL],
                tool_choice={"type": "tool", "name": "submit_review"},
                messages=[{"role": "user", "content": attempt_content}],
            )
        except anthropic.APIError as e:
            _diagnose("provider_error")
            raise ProfileReviewError("We couldn't complete this review right now. Please try again.") from e

        log_usage("spotlight", response)
        try:
            return _extract_tool_input(response)
        except ValueError as e:
            _diagnose(str(e))

    raise ProfileReviewError("We couldn't complete this review right now. Please try again.")
