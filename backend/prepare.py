"""
Prepare: an interview-preparation tool. Takes a target job description and
(optionally) the text of a candidate's resume, and produces the themes the
employer likely cares about, a set of grouped interview questions with a
plain-language reason for each one, and a few thoughtful questions the
candidate could ask the interviewer.

Same shape as coach.py: one Claude call, one structured JSON response.
"We don't invent your value. We help you see it." - so this never invents
resume content, never predicts whether the candidate will get the job, and
always hedges with "likely"/"may"/"could" rather than claiming certainty
about what a real interviewer will ask.
"""
import json
import os

import anthropic

from llm_utils import extract_final_text, extract_json_object

MODEL = os.environ.get("CT_MODEL", "claude-sonnet-5")

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

Respond ONLY with a JSON object in this exact shape, no other text, no \
markdown code fence:

{
  "employer_priorities": ["theme one", "theme two"],
  "question_groups": [
    {
      "category": "Behavioral Questions",
      "questions": [
        {
          "id": "q1",
          "question": "...",
          "why": "...",
          "source": "job_description" | "resume" | "general",
          "signal": "short quote/paraphrase, or null"
        }
      ]
    }
  ],
  "candidate_questions": ["...", "...", "...", "...", "..."],
  "prep_tip": "..."
}
"""

USER_PROMPT_TEMPLATE = """JOB DESCRIPTION:
{job_description}

RESUME TEXT:
{resume_text}

Produce the employer priorities, grouped interview questions, candidate \
questions, and prep tip as specified in the system prompt."""

NO_RESUME_PLACEHOLDER = "(no resume was provided - omit the \"Resume-Based Questions\" group entirely)"


class PrepareError(Exception):
    pass


def prepare(job_description: str, resume_text: str = "") -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PrepareError("ANTHROPIC_API_KEY is not set on the server.")

    client = anthropic.Anthropic()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        job_description=job_description,
        resume_text=resume_text.strip() if resume_text.strip() else NO_RESUME_PLACEHOLDER,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,  # extended thinking tokens count against this too
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as e:
        raise PrepareError(f"Claude API error: {e}") from e

    text = extract_final_text(response)
    try:
        return extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise PrepareError(f"Could not parse model response as JSON: {e}") from e
