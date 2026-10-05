"""
Checked resume pipeline for job-targeted builds:

  1. plan_terms()          - AI: the posting's key terms (its exact wording) and,
                             for each, whether the candidate's evidence supports it.
  2. (code guard)          - literal matches are re-checked in code, never trusted to the AI.
  3. build_tailored_resume - AI: writes the resume with the plan as the authority.
  4. check_placement()     - code: is every supported term really on the page?
  5. add_missing_terms()   - AI, only if needed: a minimal edit adding just the missing terms.
  6. term_report           - what is on the resume, what could not be placed, and which
                             posting terms the profile does not support yet.

The AI calls reuse job_match._call_with_retry (forced tool call, one retry).
If planning fails the old single-call build still runs (no report); if the
fix-up fails or comes back malformed the step-3 resume is kept.
"""
import json
import re

from career import job_match
from career.job_match import JobMatchError

MAX_TERMS = 30
MAX_TERM_WORDS = 5  # longer "terms" are sentence fragments, not keywords
SUPPORTED = ("literal", "related")

PLAN_SYSTEM_PROMPT = """You are Nova, a careful resume strategist. You are given a job posting and a candidate's verified Career Profile (plus any facts the candidate confirmed in an interview about this posting). Produce a TERM PLAN.

1. List the key skill, keyword, tool, domain and requirement phrases the posting uses, in the posting's OWN exact wording. Read requirements, responsibilities, the overview, preferred qualifications, and any skill tags or keyword run-ins (several short tags run together with no spaces, for example "clear communicationstakeholder managementproblem-solving" - split them into separate terms). Include domain and industry terms (for example fintech, financial technology, financial services, banking) and tools or technologies. Every term must be a SHORT keyword phrase a recruiter would search for: a skill, tool, technology, domain or requirement written as a noun phrase of at most 4 words (for example "proposal development," "technical expertise," "financial products," "pricing strategies," "client onboarding"). Do NOT list duties, sentences or sentence fragments (not "taking ownership of complex initiatives," not "translate complex technical concepts into clear business value," not "address technical objections"); if a duty contains a real skill, list just the short skill. Skip generic filler unless the posting states it as a requirement. At most 30 terms, most important first. Judge importance from the posting's own language: "required" (must-have or a key requirement), "preferred" (nice-to-have), or "mentioned".

2. For EACH term decide whether the candidate's evidence supports it:
- "literal": the exact term (ignoring capitalization, plurals and hyphens) appears in the Career Profile or the confirmed facts.
- "related": not literal, but the profile genuinely shows the same underlying skill or domain under different wording. Give the evidence. Examples: RFP responses support "proposal development"; being the technical advisor to treasury and IT teams supports "technical expertise"; training and coaching support "technical training"; demonstrating products and equipping sales teams supports "product education"; directing the "full sales lifecycle" or an end-to-end sales engagement supports "sales cycle" and "sales process". Domain labels count when the work substantively involves that domain: building, integrating or selling payments or banking technology (APIs, ERP/TMS bank connectivity, payment rails, real-time payments such as Zelle or FastPayments, embedded finance) supports "financial technology" and "fintech"; working at a bank supports "banking" and "financial services". Role titles are evidence too: a title containing Sales, Account, Client, Relationship or Consultant supports sales experience, customer-facing work and customer relationships.
- "none": no real support in the profile. Never stretch a term to make it fit; an honest "none" is the correct answer for something the candidate has not done.
For "literal" and "related" give a short evidence note naming the role and the phrase or activity that proves it.

Call the submit_term_plan tool. Do not respond with plain text."""

PLAN_USER_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

CONFIRMED FACTS FROM THE INTERVIEW (approved by the candidate):
{facts_text}

JOB POSTING:
{job_description}

Produce the term plan as specified in the system prompt."""

PLAN_TOOL = {
    "name": "submit_term_plan",
    "description": "Submit the posting's key terms and whether the candidate's evidence supports each.",
    "input_schema": {
        "type": "object",
        "properties": {
            "terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "description": "The posting's exact wording."},
                        "importance": {"type": "string", "enum": ["required", "preferred", "mentioned"]},
                        "support": {"type": "string", "enum": ["literal", "related", "none"]},
                        "evidence": {"type": "string", "description": "Role and phrase/activity that supports it; empty if none."},
                    },
                    "required": ["term", "importance", "support", "evidence"],
                },
            },
        },
        "required": ["terms"],
    },
}

REVISE_SYSTEM_PROMPT = """You are making a MINIMAL edit to a finished resume. You are given the resume as JSON and a list of posting terms that are supported by the candidate's real evidence but are missing from the resume.

Add each missing term using its EXACT wording, ONLY in the SKILLS section: append it to the best-fitting grouped line (a line looks like "Group label: skill, skill, skill") or add a short new group line. Do not touch the summary or any bullet. Never add a term that is already in SKILLS.

Rules: change nothing else; do not add any term that is not on the list; do not add claims, metrics, employers, titles or responsibilities; keep every experience entry. Return the COMPLETE resume_data with the same structure. Call the submit_revised_resume tool. Do not respond with plain text."""

REVISE_USER_TEMPLATE = """CURRENT RESUME (JSON):
{resume_json}

MISSING TERMS (each is backed by the candidate's real evidence):
{terms_text}

Make the minimal edit as specified in the system prompt."""

REVISE_TOOL = {
    "name": "submit_revised_resume",
    "description": "Submit the full resume after adding the missing terms.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_data": job_match.BUILD_RESUME_TOOL["input_schema"]["properties"]["resume_data"],
        },
        "required": ["resume_data"],
    },
}

_WORD = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize(text: str) -> str:
    """Lowercase, split on anything that is not a letter or digit (so hyphens and
    punctuation vanish) and strip simple plurals - so 'business-case',
    'Business Cases' and 'business case' all compare equal."""
    return " ".join(_stem(w) for w in _WORD.findall((text or "").lower()))


def term_in_text(term: str, text: str) -> bool:
    t = normalize(term)
    if not t:
        return False
    return f" {t} " in f" {normalize(text)} "


def resume_text(resume_data: dict) -> str:
    parts = [resume_data.get("headline", ""), resume_data.get("summary", "")]
    parts += list(resume_data.get("skills") or [])
    for job in resume_data.get("experience") or []:
        parts.append(job.get("title", ""))
        parts += list(job.get("bullets") or [])
    parts += list(resume_data.get("education") or [])
    parts += list(resume_data.get("certifications") or [])
    return "\n".join(str(p) for p in parts if p)


def facts_text_for(confirmed_facts: list) -> str:
    if not confirmed_facts:
        return "(none confirmed)"
    return "\n".join(f"- ({f.get('category', '')}) {f.get('bullet_text', '')}" for f in confirmed_facts)


def plan_terms(profile_text: str, facts_text: str, job_description: str) -> list[dict]:
    user_prompt = PLAN_USER_TEMPLATE.format(
        profile_text=profile_text, facts_text=facts_text, job_description=job_description
    )
    data = job_match._call_with_retry(
        "career_term_plan",
        PLAN_SYSTEM_PROMPT,
        user_prompt,
        PLAN_TOOL,
        extract=lambda r: job_match._extract_tool_input(r, "submit_term_plan", ("terms",)),
    )

    evidence_pool = profile_text + "\n" + facts_text
    terms: list[dict] = []
    seen: set[str] = set()
    for raw in (data.get("terms") or [])[:MAX_TERMS]:
        term = (raw.get("term") or "").strip()
        key = normalize(term)
        if not term or key in seen or len(key.split()) > MAX_TERM_WORDS:
            continue
        seen.add(key)

        evidence = (raw.get("evidence") or "").strip()
        support = raw.get("support", "none")
        # Code guard: the literal check is done here, not trusted to the model.
        if term_in_text(term, evidence_pool):
            support = "literal"
        elif support == "literal":
            support = "related"
        if support == "related" and not evidence:
            support = "none"  # "related" without a stated reason is not evidence

        terms.append({
            "term": term,
            "importance": raw.get("importance", "mentioned"),
            "support": support,
            "evidence": evidence,
        })
    return terms


def keyword_check(profile_text: str, confirmed_facts: list, job_description: str) -> dict:
    """The optional pre-build "keyword check": the posting's key terms that are
    NOT literally in the profile, so the candidate can say which ones they
    really have (and where it belongs) before the resume is built. Terms
    already in the profile are only counted. "related" terms carry the evidence
    the planner found; "none" terms have none. Nothing is saved here."""
    terms = plan_terms(profile_text, facts_text_for(confirmed_facts), job_description)
    rank = {"required": 0, "preferred": 1, "mentioned": 2}
    needs = [t for t in terms if t["support"] != "literal"]
    needs.sort(key=lambda t: (rank.get(t["importance"], 3), t["support"] != "related"))
    return {"terms": needs, "already_covered": len(terms) - len(needs)}


def _split_top_level(text: str) -> list[str]:
    """Split on commas and semicolons that are not inside parentheses, so
    "Data Analytics (Tableau, Power BI), CRM" keeps its parenthetical whole."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


MAX_SKILL_WORDS = 4  # a skill is a keyword, not a sentence
# Action verbs that start duties, not skills ("Taking Ownership of ...", "Articulate Business Value").
_VERB_STARTS = {
    "articulate", "address", "addressing", "translate", "translating", "taking", "working",
    "selling", "managing", "leading", "driving", "ensuring", "delivering", "partnering", "owning",
}
_PART_SPLIT = re.compile(r"\s*(?:&|/|\+|\band\b)\s*")


def _skill_word_count(item: str) -> int:
    """Words in the longest part of a skill. A compound like
    "Go-to-Market Playbook & Sales Enablement Development" is judged part by
    part; a parenthetical like "(Tableau, Power BI)" is not counted."""
    plain = re.sub(r"\([^)]*\)", " ", item.lower())
    return max((len(_WORD.findall(p)) for p in _PART_SPLIT.split(plain)), default=0)


# One-word or generic leftovers that say nothing on their own.
_GENERIC = {"strategies", "best practices", "initiatives", "solutions", "capabilities"}


def _clean_item(item: str) -> str:
    """Strip a leading 'and'/'or' left behind when a list sentence was split on commas."""
    return re.sub(r"^(?:and|or)\s+", "", item.strip(), flags=re.I)


def _looks_like_duty(item: str) -> bool:
    words = _WORD.findall(item.lower())
    return bool(words) and (words[0] in _VERB_STARTS or normalize(item) in {normalize(g) for g in _GENERIC})


def dedupe_skills(resume_data: dict) -> dict:
    """Keep the skills section to keywords only: drop sentence-like entries
    (more than MAX_SKILL_WORDS words outside parentheses), remove repeated
    skills (case, plural and hyphen insensitive) across the grouped lines, and
    drop a line left with nothing. The longer sentences stay in the profile as
    reference; they are never printed here."""
    seen: set[str] = set()
    lines: list[str] = []
    for line in resume_data.get("skills") or []:
        label, sep, rest = line.partition(":")
        grouped = bool(sep) and len(label) <= 40
        items = [_clean_item(i) for i in _split_top_level(rest if grouped else line)]
        kept = []
        for item in items:
            key = normalize(item)
            if key and key not in seen and _skill_word_count(item) <= MAX_SKILL_WORDS and not _looks_like_duty(item):
                seen.add(key)
                kept.append(item)
        if not kept:
            continue
        lines.append(f"{label.strip()}: {', '.join(kept)}" if grouped else ", ".join(kept))
    return {**resume_data, "skills": lines}


def check_placement(resume_data: dict, terms: list[dict]) -> None:
    text = resume_text(resume_data)
    for t in terms:
        t["on_resume"] = t["support"] in SUPPORTED and term_in_text(t["term"], text)


def add_missing_terms(resume_data: dict, missing: list[dict]) -> dict | None:
    """One minimal fix-up call. Returns the revised resume, or None if the
    result is unusable (the caller then keeps the original)."""
    terms_text = "\n".join(
        f"- {t['term']}" + (f"  (evidence: {t['evidence']})" if t.get("evidence") else "  (appears in the profile)")
        for t in missing
    )
    user_prompt = REVISE_USER_TEMPLATE.format(
        resume_json=json.dumps(resume_data, ensure_ascii=False), terms_text=terms_text
    )
    data = job_match._call_with_retry(
        "career_term_revise",
        REVISE_SYSTEM_PROMPT,
        user_prompt,
        REVISE_TOOL,
        extract=lambda r: job_match._extract_tool_input(r, "submit_revised_resume", ("resume_data",)),
    )
    revised = data.get("resume_data") or {}
    required = ("name", "contact", "headline", "summary", "skills", "experience", "education")
    if any(k not in revised for k in required):
        return None
    if len(revised["experience"]) != len(resume_data.get("experience") or []):
        return None
    return revised


def _status(t: dict) -> str:
    if t["support"] not in SUPPORTED:
        return "not_in_profile"
    return "on_resume" if t.get("on_resume") else "not_placed"


def build_checked_resume(profile_text: str, job_description: str, confirmed_facts: list, name: str, contact: str) -> dict:
    facts_text = facts_text_for(confirmed_facts)

    try:
        terms = plan_terms(profile_text, facts_text, job_description)
    except JobMatchError:
        terms = None  # fall back to the plain one-call build, no report

    result = job_match.build_tailored_resume(
        profile_text, job_description, confirmed_facts, name, contact, term_plan=terms
    )
    if not terms:
        result["resume_data"] = dedupe_skills(result["resume_data"])
        result["term_report"] = []
        return result

    resume = dedupe_skills(result["resume_data"])
    check_placement(resume, terms)
    missing = [t for t in terms if t["support"] in SUPPORTED and not t["on_resume"]]
    if missing:
        try:
            revised = add_missing_terms(resume, missing)
        except JobMatchError:
            revised = None
        if revised:
            resume = dedupe_skills({**resume, **revised})
            check_placement(resume, terms)
    result["resume_data"] = resume
    result["term_report"] = [
        {"term": t["term"], "importance": t["importance"], "support": t["support"],
         "evidence": t["evidence"], "status": _status(t)}
        for t in terms
    ]
    return result
