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

Do four things:

1. ASSESS how well the Career Profile matches the job posting, honestly, as "Low", "Average", or "High", the way a discerning human recruiter would - NOT by counting keyword overlap and NOT with a letter grade or numeric score. Call out cases where a word or phrase appears in both the profile and the posting but means something different in context (e.g. "cash management" at a retail bank branch vs. as a corporate treasury product). Be calibrated: most real comparisons should land as "Average". Be encouraging in TONE, never by inflating the ASSESSMENT. Frame any gap as "not yet evidenced" or "worth exploring," never as something wrong with the person - an unconfirmed qualification is a statement about the profile's current evidence, not about them.

2. Enumerate the posting's QUALIFICATION REQUIREMENTS exhaustively - go through the actual posting text and identify every distinct skill, experience, credential, or qualification it states or clearly implies, not just the first few that stand out. Classify each one's IMPORTANCE based on the posting's own language: "required" (stated as required/must-have, or essential to the role as described) or "preferred" (stated as preferred/nice-to-have/a plus). For each requirement the Career Profile does not yet clearly evidence, record it as a REQUIRED QUALIFICATION GAP with that importance, marked "missing" or "partial," with a plain explanation. Leave out requirements the profile already clearly evidences - this list should end up being every genuine gap, not a sampled few, so nothing important silently slips through.

3. Write a FIRST BATCH of yes/no discovery questions to find out if the candidate actually has relevant experience that just isn't in their profile yet - specific and grounded in this posting's actual requirements, never generic. PRIORITIZE "required"-importance gaps first; only include "preferred"-importance gaps in this first batch if there's room after covering every required gap. Include at most 6 questions in this first batch - if there are more required gaps than fit, the remaining ones will be covered in follow-up rounds (see below), never dropped. Each question must be answerable honestly with yes/no. Never assume yes. This batch must never be empty when there are real gaps to explore, and must never skip a required-importance gap in favor of a preferred one.

4. Extract a short JOB TITLE label for this posting - e.g. "Senior Software Engineer at Acme Corp" - or a brief descriptive phrase if the posting doesn't plainly state a title/employer (e.g. "Retail Store Manager role").

The CATEGORIES you submit must name each specific gap you identified in step 2 (both required and preferred), not generic buckets - e.g. "Franchise compliance auditing (required)" or "Bilingual client support (preferred)," not just "Compliance." List required-importance gaps first. A later follow-up interview works through this list in order to make sure every gap eventually gets asked about, so anything you leave out or mislabel here will never get asked about.

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
                "importance": {
                    "type": "string",
                    "enum": ["required", "preferred"],
                    "description": "Per the posting's own language - required/must-have, or preferred/nice-to-have.",
                },
                "status": {"type": "string", "enum": ["missing", "partial"]},
                "explanation": {"type": "string"},
            },
            "required": ["requirement", "importance", "status", "explanation"],
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

ATS TERMINOLOGY (applies most to the SKILLS section): applicant tracking systems and recruiters search on literal keyword/phrase matches, not paraphrases - meaning the same thing in different words still scores as a miss. When the evidence genuinely supports it, use the exact standard industry term a recruiter or ATS would search for (e.g. "Risk Management," "Corporate Banking," "Customer Relationship Management") as its own clean skill phrase, not only folded into a longer descriptive sentence elsewhere. This includes DERIVING a standard skill label from what an EXPERIENCE bullet already describes, even if that exact term never appears verbatim - restating already-described activity as its standard name is using supplied content, not inventing it. For example, a bullet describing "managed a treasury client portfolio for large corporate clients" directly supports "Customer Relationship Management" as a skill entry, and in a sales/advisory context also supports "Consultative Selling" - both belong in SKILLS even though neither phrase was typed verbatim anywhere in the profile. Likewise, a bullet describing "presented on panels addressing risk, automation, and the future of payments and served on an advisory board to inform product strategy" directly supports "Presentation Skills" (or "Public Speaking") and "Advisory Board Participation" (or "Industry Thought Leadership") as their own skill entries - do not leave this kind of activity sitting only as narrative text under EXPERIENCE when it clearly supports a standard skill phrase. Apply this same derivation to EVERY bullet across EVERY role, not just one or two - a skill phrase belongs in SKILLS whenever any bullet anywhere in the profile genuinely supports it, not only when it's convenient. Never use a term the underlying activity doesn't actually support just because it sounds standard for the field.

POSTING TERMINOLOGY (this is what lets a recruiter or ATS see that the skills are there): before writing, read the job posting and list the key skill and keyword phrases it uses - in its requirements, responsibilities, overview, and any skill tags or keyword run-ins it contains. For EACH one, check the Career Profile for evidence of the same underlying skill, even when the profile words it differently (for example: posting "product adoption" vs. profile "platform adoption" or "supporting adoption"; "customer relationships" vs. "executive relationship management" or managing a client portfolio; "competitive landscape" vs. "competitive positioning analysis" or "competitive analysis"; "strategic selling" vs. "strategic account planning" or "consultative selling"; "business cases" vs. "business-case development"; "customer-facing" vs. client-facing roles). Where the evidence supports it, use the posting's OWN wording, matched exactly (same words, same singular/plural, same hyphenation), as its own entry in SKILLS and, where it reads naturally, once in the summary or a bullet. Where the profile has NO evidence for a posting term (for example a technology or industry the candidate has never worked in), leave it out entirely - never add it to look like a better match. This is aligning the wording of skills the candidate really has, not keyword stuffing: do not repeat a term more than it needs.

TARGET TITLE: if a TARGET JOB TITLE is given, you may state it once as the candidate's target role, in the headline or the first line of the summary (for example "Targeting: <title>"). It must never appear as a title the candidate held, never inside an EXPERIENCE entry or bullet, and never be described as past work, unless that exact title is already in the Career Profile.

TITLES AND EMPLOYERS ARE EVIDENCE: a role title in the profile is itself proof of the core skills that title requires, even when no bullet repeats them. A title containing Sales, Account, Client, Relationship or Consultant (or managing a client-facing function) evidences sales experience, customer-facing work, and customer/client relationships; a multi-year history of such titles supports stating those skills plainly and confidently in SKILLS (for example "Sales Experience," "Customer-Facing Account Management," "Customer Relationships"). Treat them as supported - do not omit them because no single bullet uses the exact words. This applies only to skills the titles genuinely imply; never stretch a title to cover a different specialty.

Build the resume:
1. A POSITIONING HEADLINE: 2-3 short pipe-separated capitalized phrases capturing the candidate's professional identity relevant to this job, supported only by their real experience.
2. A PROFESSIONAL SUMMARY (3-5 lines) connecting their real background to this specific posting.
3. SKILLS: a list of skills/expertise phrases drawn from the Career Profile plus whatever the confirmed facts demonstrate, prioritized for relevance to this posting, using exact standard terminology per the ATS note above wherever the evidence supports it.
4. EXPERIENCE: each role's bullets, prioritized and polished for relevance to this posting, confirmed facts folded into the right role.
5. EDUCATION and CERTIFICATIONS: pass through from the Career Profile unchanged.

Call the submit_tailored_resume tool with the resume. Do not respond with plain text."""

BUILD_RESUME_USER_PROMPT_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

TARGET JOB POSTING:
{job_description}

TARGET JOB TITLE: {target_job_title}

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


GENERAL_RESUME_SYSTEM_PROMPT = """You are Nova, an expert executive resume writer, building a general resume straight from a candidate's verified Career Profile. There is no specific job posting to tailor to this time - the Career Profile itself (real roles, education, certifications, skills they've already confirmed) is the ONLY source of truth. Nothing else may be added.

FACTUAL SAFETY RULES (non-negotiable):
Never invent skills, technologies, employers, job titles, metrics, revenue, team sizes, certifications, education, products, responsibilities, leadership scope, client types, awards, or years of experience. Only the supplied Career Profile content may appear. If something is uncertain, leave it out.
Never promote participation into ownership: if source text says "supported" do not write "led"; if it says "partnered with" do not write "owned".

SCOPE (this is an organize-and-polish task, not a selection task):
Unlike a job-targeted resume, do not prioritize or drop content for relevance to any particular posting - include every real role from the Career Profile. Use judgment about ordering and which skills/bullets to foreground within a role, but the goal is a complete, broadly strong resume, not a narrowed one.

WRITING STYLE:
Senior, polished, confident, concise, human. Avoid repetitive AI resume language such as "results-driven," "dynamic," "highly motivated," "proven track record," or "hard-working" unless truly appropriate given the evidence.

ATS TERMINOLOGY (applies most to the SKILLS section): applicant tracking systems and recruiters search on literal keyword/phrase matches, not paraphrases - meaning the same thing in different words still scores as a miss. When the evidence genuinely supports it, use the exact standard industry term a recruiter or ATS would search for (e.g. "Risk Management," "Corporate Banking," "Customer Relationship Management") as its own clean skill phrase, not only folded into a longer descriptive sentence elsewhere. This includes DERIVING a standard skill label from what an EXPERIENCE bullet already describes, even if that exact term never appears verbatim - restating already-described activity as its standard name is using supplied content, not inventing it. For example, a bullet describing "managed a treasury client portfolio for large corporate clients" directly supports "Customer Relationship Management" as a skill entry, and in a sales/advisory context also supports "Consultative Selling" - both belong in SKILLS even though neither phrase was typed verbatim anywhere in the profile. Likewise, a bullet describing "presented on panels addressing risk, automation, and the future of payments and served on an advisory board to inform product strategy" directly supports "Presentation Skills" (or "Public Speaking") and "Advisory Board Participation" (or "Industry Thought Leadership") as their own skill entries - do not leave this kind of activity sitting only as narrative text under EXPERIENCE when it clearly supports a standard skill phrase. Apply this same derivation to EVERY bullet across EVERY role, not just one or two - a skill phrase belongs in SKILLS whenever any bullet anywhere in the profile genuinely supports it, not only when it's convenient. Never use a term the underlying activity doesn't actually support just because it sounds standard for the field.

TITLES AND EMPLOYERS ARE EVIDENCE: a role title in the profile is itself proof of the core skills that title requires, even when no bullet repeats them. A title containing Sales, Account, Client, Relationship or Consultant (or managing a client-facing function) evidences sales experience, customer-facing work, and customer/client relationships; a multi-year history of such titles supports stating those skills plainly and confidently in SKILLS (for example "Sales Experience," "Customer-Facing Account Management," "Customer Relationships"). Treat them as supported - do not omit them because no single bullet uses the exact words. This applies only to skills the titles genuinely imply; never stretch a title to cover a different specialty.

Build the resume:
1. A POSITIONING HEADLINE: 2-3 short pipe-separated capitalized phrases capturing the candidate's professional identity, supported only by their real experience.
2. A PROFESSIONAL SUMMARY (3-5 lines) reflecting their real background as a whole.
3. SKILLS: a polished, deduplicated list of skills/expertise phrases drawn from the Career Profile, using exact standard terminology per the ATS note above wherever the evidence supports it.
4. EXPERIENCE: every role from the Career Profile, with polished bullets - no role dropped.
5. EDUCATION and CERTIFICATIONS: pass through from the Career Profile unchanged.

Call the submit_general_resume tool with the resume. Do not respond with plain text."""

GENERAL_RESUME_USER_PROMPT_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

CANDIDATE NAME: {name}
CANDIDATE CONTACT LINE: {contact}

Produce the general resume as specified in the system prompt."""

GENERAL_RESUME_TOOL = {
    "name": "submit_general_resume",
    "description": "Submit the general resume in the standard format.",
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


def build_tailored_resume(profile_text: str, job_description: str, confirmed_facts: list, name: str, contact: str, target_job_title: str | None = None) -> dict:
    facts_text = (
        "\n".join(f"- ({f.get('category', '')}) {f.get('bullet_text', '')}" for f in confirmed_facts)
        if confirmed_facts
        else "(none confirmed - use only the Career Profile itself)"
    )
    user_prompt = BUILD_RESUME_USER_PROMPT_TEMPLATE.format(
        profile_text=profile_text,
        job_description=job_description,
        target_job_title=target_job_title or "(not given)",
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


def build_general_resume(profile_text: str, name: str, contact: str) -> dict:
    user_prompt = GENERAL_RESUME_USER_PROMPT_TEMPLATE.format(profile_text=profile_text, name=name, contact=contact)
    return _call_with_retry(
        "career_general_resume",
        GENERAL_RESUME_SYSTEM_PROMPT,
        user_prompt,
        GENERAL_RESUME_TOOL,
        extract=lambda r: _extract_tool_input(r, "submit_general_resume", ("resume_data",)),
    )
