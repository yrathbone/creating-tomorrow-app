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

from career import job_match, provenance, resume_quality
from career.job_match import JobMatchError

MAX_TERMS = 60  # long postings have 40+ distinct terms (one real posting filled 45 of 45); scanners such as Jobscan count them all
_HEDGED_EVIDENCE = re.compile(
    r"\b(however|has not|have not|hasn't|haven't|does not|doesn't|not held|no direct|no formal|different|adjacent|rather than|not the same"
    r"|(?:though|although|but|yet)\s+not|not\s+(?:specifically|exactly|directly|really|quite)|only\s+loosely|loosely)\b", re.I)
MAX_TERM_WORDS = 5  # longer "terms" are sentence fragments, not keywords
SUPPORTED = ("literal", "related")
TRANSFERABLE = "transferable"  # a real, different activity behind a skill the posting values; never claims the posting's own specialised wording

PLAN_SYSTEM_PROMPT = """You are Nova, a careful resume strategist. You are given a job posting and a candidate's verified Career Profile (plus any facts the candidate confirmed in an interview about this posting). Produce a TERM PLAN.

1. List the key skill, keyword, tool, domain and requirement phrases the posting uses, in the posting's OWN exact wording. Read requirements, responsibilities, the overview, preferred qualifications, and any skill tags or keyword run-ins (several short tags run together with no spaces, for example "clear communicationstakeholder managementproblem-solving" - split them into separate terms). Include domain and industry terms (for example fintech, financial technology, financial services, banking) and tools or technologies. Every term must be a SHORT keyword phrase a recruiter would search for: a skill, tool, technology, domain or requirement written as a noun phrase of at most 4 words (for example "proposal development," "technical expertise," "financial products," "pricing strategies," "client onboarding"). Do NOT list duties, sentences or sentence fragments (not "taking ownership of complex initiatives," not "translate complex technical concepts into clear business value," not "address technical objections"); if a duty contains a real skill, list just the short skill. Skip generic filler unless the posting states it as a requirement. At most 60 terms, most important first. Scanners also normalise wording into standard skill names, so when a duty or requirement sentence implies a recognised skill, ALSO list that standard skill name as its own term (for example "building strong relationships with customers" -> "relationship management"; "taking ownership of complex initiatives" -> "strategic initiatives"; "technical conversations with executives" -> "technical expertise"). Evidence is judged for these exactly like any other term, so an unsupported one is simply marked "none". Include the soft skills and competencies the posting names (for example "relationship management," "communication skills," "stakeholder management") as terms too; scanners count them. Judge importance from the posting's own language: "required" (must-have or a key requirement), "preferred" (nice-to-have), or "mentioned". Also give each term a kind: "skill" = a skill, tool, system, method or industry/domain a recruiter would list in a skills section (for example "proposal development," "ERP integrations," "fintech," "customer success"); "phrase" = context or duty wording that is not a skill by itself (for example "sales setting," "difficult customers," "business sense," "achieving targets and goals," "large, global, complex organizations," "complex projects and programs"). A recognised skill, competency, business process, methodology or domain is ALWAYS kind "skill", even when it sounds like a duty or a soft skill: for example "sales cycle," "sales process," "strategic initiatives," "relationship management," "stakeholder management," "technical expertise," "communication skills," "pipeline management," "account management," "forecasting." When unsure, choose "skill": a skill is placed on the resume (only if the candidate's evidence supports it), while a phrase is kept off the skills list. Do list the skill or domain inside the posting's own job title as a term (for example "customer success" for a Customer Success Manager role); the posting's title is a strong signal of what it wants.

ALTERNATIVES: when the posting says any ONE of several qualifications will do (for example "PMP, PRINCE2 or equivalent project delivery experience", "AWS or Azure certification", "a degree or equivalent experience"), give those terms the SAME short alternatives_group label (lowercase, for example "project-management-credential") and list each alternative as its own term. Set accepts_equivalent_experience true only when the posting itself says equivalent experience is accepted. Leave both fields out for ordinary requirements; two separate requirements are NOT alternatives. Grouping never changes the evidence judgement: a credential is "literal" or "related" only when the profile actually shows it, and experience is never relabelled as holding a certification.

2. For EACH term decide whether the candidate's evidence supports it:
- "literal": the exact term (ignoring capitalization, plurals and hyphens) appears in the Career Profile or the confirmed facts.
- "related": not literal, but the profile genuinely shows the SAME underlying activity, skill or domain under different wording. RELATED MEANS THE SAME ACTIVITY IN OTHER WORDS, never a similar-looking or lesser activity. Never relabel one kind of work as another: a lesson video is not an e-learning module, screen recording is not video editing, mentoring a colleague is not working with subject matter experts, classroom teaching is not corporate training, handling cash at a retail register is not bank-teller compliance work. When the evidence is only an adjacent or weaker activity, answer "transferable" or "none", never "related". Give the evidence. Examples: RFP responses support "proposal development"; being the technical advisor to treasury and IT teams supports "technical expertise"; training and coaching support "technical training"; demonstrating products and equipping sales teams supports "product education"; directing the "full sales lifecycle" or an end-to-end sales engagement supports "sales cycle" and "sales process"; account management, client onboarding, adoption and post-sales or renewal work supports "customer success". Domain labels count when the work substantively involves that domain: building, integrating or selling payments or banking technology (APIs, ERP/TMS bank connectivity, payment rails, real-time payments such as Zelle or FastPayments, embedded finance) supports "financial technology" and "fintech"; working at a bank supports "banking" and "financial services". Role titles are evidence too: a title containing Sales, Account, Client, Relationship or Consultant supports sales experience, customer-facing work and customer relationships.
- "transferable": the candidate's evidence shows a REAL but DIFFERENT activity that builds a skill the posting values (for example processing purchases, handling cash and assisting customers at a retail register build cash handling, transaction accuracy and customer service that matter for a bank teller role). The posting's own specialised wording is NOT claimed. Name the real activity in the evidence note. Use it only when the activity truly demonstrates the underlying skill.
- "none": no real support in the profile. Never stretch a term to make it fit; an honest "none" is the correct answer for something the candidate has not done, and for anything the candidate explicitly said no to.
For "literal", "related" and "transferable" give a short evidence note naming the role and the phrase or activity that proves it.

THE CANDIDATE'S EXPLICIT NO ANSWERS: the request lists questions the candidate answered NO. A term that IS the denied activity is "none", even when a loosely similar activity exists. A denial covers only what the question asked: do not mark a different, genuinely evidenced activity "none" just because it shares a word (a no to working with corporate subject matter experts does not erase evidence of collaborating with classroom teachers). A skipped or unanswered question is NOT evidence in either direction; never treat it as a yes. The posting is a source of what is relevant, never of facts about the candidate.

Call the submit_term_plan tool. Do not respond with plain text."""

PLAN_USER_TEMPLATE = """CANDIDATE'S CAREER PROFILE (verified, already-confirmed evidence):
{profile_text}

CONFIRMED FACTS FROM THE INTERVIEW (approved by the candidate):
{facts_text}

THE CANDIDATE EXPLICITLY ANSWERED NO TO THESE (a skipped question is not listed and is not evidence):
{denials_text}

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
                        "kind": {"type": "string", "enum": ["skill", "phrase"]},
                        "support": {"type": "string", "enum": ["literal", "related", "transferable", "none"]},
                        "evidence": {"type": "string", "description": "Role and phrase/activity that supports it; empty if none."},
                        "alternatives_group": {"type": "string", "description": "Optional. The same short label on every term of a set where the posting accepts any ONE of them."},
                        "accepts_equivalent_experience": {"type": "boolean", "description": "Optional. True only when the posting says equivalent experience is accepted for this set."},
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
    # Only what the candidate confirmed. The interview's topic label ("Video Production") is a heading for the question, never evidence, so
    # it is not part of the text the planner and the checks read.
    return "\n".join(f"- {f.get('bullet_text', '')}" for f in confirmed_facts)


def _require_term_shape(data: dict) -> dict:
    """A term list entry returned as plain text would crash plan_terms; reject
    it as ValueError so the model gets its one retry (see job_match)."""
    terms = data.get("terms")
    if not isinstance(terms, list) or any(not isinstance(t, dict) for t in terms):
        raise ValueError("invalid_shape")
    return data


def posting_title(job_description: str) -> str:
    """The job title a posting opens with: its first line, when that is short and not a sentence (an optional "Job title:" label is
    dropped). Empty when the first line does not look like a title. Used to enforce "never state the target" in code."""
    for line in (job_description or "").splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^(?:job\s*title|position|role)\s*[:\-]\s*", "", line, flags=re.I)
        words = line.split()
        if 1 <= len(words) <= 6 and not re.search(r"[.!?;]", line):
            return line
        return ""
    return ""


def denials_text_for(denials: list[dict] | None) -> str:
    if not denials:
        return "(none)"
    return "\n".join(f"- {d['question']}" for d in denials)


def plan_terms(profile_text: str, facts_text: str, job_description: str, denials: list[dict] | None = None) -> list[dict]:
    user_prompt = PLAN_USER_TEMPLATE.format(
        profile_text=profile_text, facts_text=facts_text, job_description=job_description,
        denials_text=denials_text_for(denials),
    )
    data = job_match._call_with_retry(
        "career_term_plan",
        PLAN_SYSTEM_PROMPT,
        user_prompt,
        PLAN_TOOL,
        extract=lambda r: _require_term_shape(job_match._extract_tool_input(r, "submit_term_plan", ("terms",))),
    )
    return guard_terms(data.get("terms") or [], profile_text, facts_text, job_description, denials)


def reguard_saved_terms(saved: list[dict], profile_text: str, facts_text: str, job_description: str, denials: list[dict] | None = None) -> list[dict]:
    """Re-checks a plan saved by the keyword step against the evidence as it is NOW (no AI call): every code guard runs again, so a term
    the candidate has since confirmed becomes literal, a new denial removes support, and a literal term that is no longer in the evidence
    is never carried as supported. The model's judgement is reused only for "related"/"transferable" notes, which still need their reason."""
    pool = profile_text + "\n" + facts_text
    raws = [{**t, "support": "none" if t.get("support") == "literal" and not term_in_text(t.get("term", ""), pool) else t.get("support", "none")}
            for t in saved if isinstance(t, dict)]
    return guard_terms(raws, profile_text, facts_text, job_description, denials)


def guard_terms(raw_terms: list[dict], profile_text: str, facts_text: str, job_description: str, denials: list[dict] | None = None) -> list[dict]:
    """Turns the planner's raw terms into the guarded plan: the code decides literal support, drops unevidenced or hedged "related", applies
    the candidate's explicit No answers and the posting-title rule, and keeps only real alternatives groups."""
    evidence_pool = profile_text + "\n" + facts_text
    terms: list[dict] = []
    seen: set[str] = set()
    for raw in raw_terms[:MAX_TERMS]:
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
        if support in ("related", TRANSFERABLE) and not evidence:
            support = "none"  # "related" or "transferable" without a stated reason is not evidence
        if support == "related" and _HEDGED_EVIDENCE.search(evidence):
            support = TRANSFERABLE  # the model's own note says it is a different or adjacent activity: that is "transferable", never "same activity"
        if support not in ("literal", "related", TRANSFERABLE):
            support = "none"

        # Code guard for the candidate's explicit No answers: a term that sits entirely inside what the candidate denied is
        # never supported, whatever the model said. The match is by scope (every distinctive word of the term), so an adjacent,
        # genuinely evidenced activity that merely shares one word is NOT removed.
        denial = resume_quality.denied_by(term, denials or [])
        if denial is not None and support != "none":
            support, evidence = "none", ""

        kind = "phrase" if raw.get("kind") == "phrase" else "skill"
        terms.append({
            "term": term,
            "kind": kind,
            "importance": raw.get("importance", "mentioned"),
            "support": support,
            "evidence": evidence,
            "denied": denial is not None,
            "alternatives_group": normalize(str(raw.get("alternatives_group") or ""))[:40],
            "accepts_equivalent_experience": raw.get("accepts_equivalent_experience") is True,
        })
    # The posting's own job title is where the candidate is APPLYING, not something they hold: unless the evidence literally says it,
    # a term equal to the title is never supported (it was marked "related" in the live Daniel rerun, and the writer then called him
    # an "Instructional Designer").
    title = posting_title(job_description)
    if title:
        for t in terms:
            if t["support"] != "literal" and normalize(t["term"]) == normalize(title):
                t["support"], t["evidence"] = "none", ""
        # A term that is the heart of the title ("customer success" in "Customer Success Associate") is the role being applied for: unless the
        # evidence literally says it, "related" is never enough to print it as the candidate's own skill. It stays a question.
        title_words = set(normalize(title).split())
        for t in terms:
            words = set(normalize(t["term"]).split())
            if t["support"] == "related" and len(words) >= 2 and words <= title_words:
                t["support"] = TRANSFERABLE
    # An alternatives group needs at least two skill terms; a lone label is an ordinary requirement.
    sizes: dict[str, int] = {}
    for t in terms:
        if t["alternatives_group"] and t["kind"] != "phrase":
            sizes[t["alternatives_group"]] = sizes.get(t["alternatives_group"], 0) + 1
    for t in terms:
        if sizes.get(t["alternatives_group"], 0) < 2 or t["kind"] == "phrase":
            t["alternatives_group"], t["accepts_equivalent_experience"] = "", False
    return terms


TIDY_MIN_WORDS = 3  # names this long are probably labels or sentences, not keywords
TIDY_MAX_KEYWORD_WORDS = 3

TIDY_SYSTEM_PROMPT = """You shorten the NAMES of a candidate's saved skills into resume keywords. For each skill you get an id, its current name, and the sentence describing how it was used. Return, for each id, the short keyword a recruiter would search for: 1 to 3 words, a noun phrase (for example "Sales Enablement", "CRM", "Contract Negotiation", "RFP Responses", "Sales Forecasting", "Crisis Management").

Rules:
- Use only what the current name and sentence say. Never add a skill, tool, or claim that is not already there.
- Never start with a verb or "ability to". Do not include the employer or role.
- If the name is already a good short keyword, return it unchanged.
- If the "skill" is really a certification or a goal rather than a skill, return the plain certification or topic name.
Call the submit_skill_keywords tool. Do not respond with plain text."""

TIDY_TOOL = {
    "name": "submit_skill_keywords",
    "description": "Submit a short keyword for each skill id.",
    "input_schema": {
        "type": "object",
        "properties": {
            "skills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "keyword": {"type": "string"}},
                    "required": ["id", "keyword"],
                },
            },
        },
        "required": ["skills"],
    },
}


def tidy_candidates(skills: list[dict]) -> list[dict]:
    """Saved skills whose name is longer than a keyword."""
    return [s for s in skills if len(_WORD.findall((s.get("name") or "").lower())) >= TIDY_MIN_WORDS]


def suggest_skill_keywords(skills: list[dict]) -> dict[int, str]:
    """AI-proposed short names for the given skills ({id, name, source_text}).
    Code guard: a suggestion that is empty, too long, or verb-first is dropped.
    Nothing is saved; the candidate reviews every suggestion."""
    if not skills:
        return {}
    listing = "\n".join(
        f"- id {s['id']}: name: {s['name']} | sentence: {s.get('source_text') or '(none)'}" for s in skills
    )
    data = job_match._call_with_retry(
        "career_skill_tidy",
        TIDY_SYSTEM_PROMPT,
        "SKILLS:\n" + listing,
        TIDY_TOOL,
        extract=lambda r: job_match._extract_tool_input(r, "submit_skill_keywords", ("skills",)),
    )
    valid_ids = {s["id"] for s in skills}
    out: dict[int, str] = {}
    for item in data.get("skills") or []:
        try:
            sid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        keyword = _clean_item((item.get("keyword") or "").strip())
        if sid in valid_ids and keyword and len(_WORD.findall(keyword.lower())) <= TIDY_MAX_KEYWORD_WORDS and not _looks_like_duty(keyword):
            out[sid] = keyword
    return out


def _merge_contained_questions(questions: list[dict], rank: dict) -> list[dict]:
    """One card, not two, for "SaaS" and "SaaS experience": a plain question whose words are all inside another plain question is
    dropped, and the longer one keeps the stronger importance. Group questions and differently-worded terms are untouched."""
    plain = [q for q in questions if not q.get("alternatives")]
    words = {id(q): set(normalize(q["term"]).split()) for q in plain}
    dropped: set[int] = set()
    for small in plain:
        for big in plain:
            if small is big or id(big) in dropped or not words[id(small)] < words[id(big)]:
                continue
            if rank.get(small["importance"], 3) < rank.get(big["importance"], 3):
                big["importance"] = small["importance"]
            dropped.add(id(small))
            break
    return [q for q in questions if id(q) not in dropped]


def keyword_check(profile_text: str, confirmed_facts: list, job_description: str) -> dict:
    """The optional pre-build "keyword check". The posting's key terms are split by what the candidate's own evidence already says,
    so only real gaps become questions:

      covered_exact    the term is in the profile or a confirmed fact (counted, never asked);
      covered_related  the same activity is in the profile under other words; the planner named the evidence and the code kept it only
                       because it had a reason. Listed with that evidence so the candidate can see why, never asked;
      terms            the questions: terms with no evidence ("none") and terms where only a different activity is evidenced
                       ("transferable"). Required first.

    Context phrases are never worth a question. Nothing is saved here and nothing is promoted: "related" stays related, the build step
    uses it exactly as before. "already_covered" is the number of terms that need no answer (exact plus related)."""
    return keyword_check_with_plan(profile_text, confirmed_facts, job_description)[0]


def keyword_check_with_plan(profile_text: str, confirmed_facts: list, job_description: str) -> tuple[dict, list[dict]]:
    """keyword_check, plus the guarded plan it was made from, so the route can keep the plan with the job comparison and the build can reuse
    it instead of asking the AI the same question again."""
    terms = plan_terms(profile_text, facts_text_for(confirmed_facts), job_description)
    return _split_plan(terms), terms


def _split_plan(terms: list[dict]) -> dict:
    rank = {"required": 0, "preferred": 1, "mentioned": 2}
    skills = [t for t in terms if t.get("kind") != "phrase"]
    exact = [t for t in skills if t["support"] == "literal"]
    related = [t for t in skills if t["support"] == "related" and t.get("evidence")]
    questions = [t for t in skills if t["support"] != "literal" and not (t["support"] == "related" and t.get("evidence"))]
    questions.sort(key=lambda t: (rank.get(t["importance"], 3), t["support"] != TRANSFERABLE))
    related.sort(key=lambda t: rank.get(t["importance"], 3))
    exact.sort(key=lambda t: rank.get(t["importance"], 3))
    phrases = [t for t in terms if t.get("kind") == "phrase"]

    # Alternatives ("PMP, PRINCE2 or equivalent"): the posting accepts any ONE. When one member is already backed by the profile the others
    # need no answer; when none is, the group is ONE question, not one per member. Nothing is promoted: a member is "met" only through its
    # own evidence, so a credential is never claimed for experience.
    groups: dict[str, list[dict]] = {}
    for t in skills:
        if t.get("alternatives_group"):
            groups.setdefault(t["alternatives_group"], []).append(t)
    alternatives = []
    for members in groups.values():
        names = [m["term"] for m in members]
        best = min((m["importance"] for m in members), key=lambda i: rank.get(i, 3))
        met = next((m for m in members if m in exact or m in related), None)
        questions = [q for q in questions if q not in members]
        entry = {"terms": names, "importance": best, "accepts_equivalent_experience": any(m.get("accepts_equivalent_experience") for m in members)}
        if met is not None:
            alternatives.append({**entry, "met_by": met["term"], "evidence": met["evidence"] if met["support"] == "related" else ""})
            continue
        near = next((m for m in members if m["support"] == TRANSFERABLE), None)
        questions.append({
            "term": " or ".join(names), "kind": "skill", "importance": best, "support": TRANSFERABLE if near else "none",
            "evidence": near["evidence"] if near else "", "alternatives": names,
            "accepts_equivalent_experience": entry["accepts_equivalent_experience"],
        })
    questions = _merge_contained_questions(questions, rank)
    questions.sort(key=lambda t: (rank.get(t["importance"], 3), t["support"] != TRANSFERABLE))
    return {
        "terms": questions,
        "already_covered": len(exact) + len(related) + len(phrases),
        "covered_exact": [{"term": t["term"], "importance": t["importance"]} for t in exact],
        "covered_related": [{"term": t["term"], "importance": t["importance"], "evidence": t["evidence"]} for t in related],
        "alternatives_met": alternatives,
    }


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


def dedupe_skills(resume_data: dict, wording_terms: set[str] | None = None) -> dict:
    """Keep the skills section to keywords only: drop sentence-like entries
    (more than MAX_SKILL_WORDS words outside parentheses), remove repeated
    skills (case, plural and hyphen insensitive) across the grouped lines, and
    drop a line left with nothing. The longer sentences stay in the profile as
    reference; they are never printed here. wording_terms are normalized posting
    phrases (context wording, not skills) that must never appear in this section."""
    seen: set[str] = set(wording_terms or ())
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
        t["on_resume"] = (t["support"] in SUPPORTED or t["support"] == TRANSFERABLE) and term_in_text(t["term"], text)


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
        extract=lambda r: job_match.require_resume_shape(job_match._extract_tool_input(r, "submit_revised_resume", ("resume_data",))),
    )
    revised = data.get("resume_data") or {}
    required = ("name", "contact", "headline", "summary", "skills", "experience", "education")
    if any(k not in revised for k in required):
        return None
    if len(revised["experience"]) != len(resume_data.get("experience") or []):
        return None
    return revised


def _status(t: dict) -> str:
    if t["support"] == TRANSFERABLE:
        # a real, different activity: shown to the candidate as relevant experience to build on, never as a claimed qualification
        return "on_resume" if t.get("on_resume") else "transferable"
    if t["support"] not in SUPPORTED:
        return "not_in_profile"
    if t.get("on_resume"):
        return "on_resume"
    # Context wording is only used where a sentence already says it; not using it is fine.
    return "wording_unused" if t.get("kind") == "phrase" else "not_placed"


POLISH_SYSTEM_PROMPT = """You are making a MINIMAL edit to a finished resume so it reads like a person wrote it and stays strictly true to the candidate's evidence. You are given the resume as JSON, the candidate's EVIDENCE (the only source of truth), the posting keywords that must stay on the resume, and a list of FLAGGED ITEMS, each with where it is, the exact text, and the problem.

Fix ONLY the flagged items:
- Too long or run-on: split into shorter sentences or tighten. Cut filler and repeated words. Prefer plain verbs over a string of nouns. No more than one dash in a sentence.
- Too many keywords in one sentence: keep the sentence's real meaning, spread keywords over neighbouring sentences or drop the repeat from this one. Never delete a keyword from the resume altogether: every KEEP keyword must still appear on the resume in its exact wording (the skills section already carries most of them).
- A figure or name that is not in the evidence: delete it, or restate the sentence using only what the evidence says.
- An unsupported claim (a qualification the evidence does not establish, or one the candidate said no to): take the claim out and keep what the evidence DOES say about that activity, in the candidate's own plain wording (for example keep "recorded 60 short lesson videos shared in Google Classroom" and drop "e-learning modules"). Never replace it with another unsupported claim, and never keep a keyword in a sentence if it changes what the candidate did.
Never add a fact, number, name, tool, title, employer, scope or result that is not in the EVIDENCE. Never turn "supported" into "led". Do not touch the skills list, education, certifications, headline, or any item that was not flagged. Keep every role and every bullet (rewrite a bullet in place; do not delete one unless the problem says to remove its content). Return the COMPLETE resume_data with the same structure. Call the submit_revised_resume tool. Do not respond with plain text."""

POLISH_USER_TEMPLATE = """CURRENT RESUME (JSON):
{resume_json}

CANDIDATE EVIDENCE (the only source of truth):
{evidence}

KEEP THESE POSTING KEYWORDS ON THE RESUME (exact wording):
{keep_terms}

FLAGGED ITEMS:
{issues_text}

Make the minimal edit as specified in the system prompt."""


def _prose_signature(resume_data: dict) -> list[str]:
    return [u["text"] for u in resume_quality.prose_units(resume_data)]


def improve_readability(resume_data: dict, evidence_text: str, terms: list[dict], unsupported_terms: list[str] | None = None) -> tuple[dict, dict]:
    """Truth and readability checks (career/resume_quality.py), and at most ONE targeted edit pass when they find problems.

    The edit is accepted only if it (a) keeps the same roles and bullets, (b) loses no posting term that was on the resume,
    (c) leaves fewer problems than before and (d) introduces no new truth problem. Otherwise the original resume is kept.
    Returns (resume, info) where info says what was found and what happened; it never raises."""
    info = {"found": 0, "remaining": 0, "edited": False}
    supported = [t for t in terms if t["support"] in SUPPORTED]
    skill_names = [t["term"] for t in supported if t.get("kind") != "phrase"]
    extra = "\n".join(t["term"] + " " + (t.get("evidence") or "") for t in supported)

    def check(resume):
        return (resume_quality.find_issues(resume, evidence_text, skill_names, term_in_text, extra)
                + resume_quality.find_claim_issues(resume, unsupported_terms or [], evidence_text))

    def truth_count(issues):
        return sum(1 for i in issues if "not in the candidate's profile" in i["problem"] or i["problem"].startswith("unsupported claim"))

    try:
        issues = check(resume_data)
        info["found"] = info["remaining"] = len(issues)
        if not issues:
            return resume_data, info
        keep = [t["term"] for t in supported if term_in_text(t["term"], resume_text(resume_data))]
        issues_text = "\n".join(f"- [{i['where']}] {i['problem']}\n  TEXT: {i['text']}" for i in issues[:25])
        user_prompt = POLISH_USER_TEMPLATE.format(
            resume_json=json.dumps(resume_data, ensure_ascii=False),
            evidence=evidence_text,
            keep_terms="\n".join(f"- {k}" for k in keep) or "(none)",
            issues_text=issues_text,
        )
        data = job_match._call_with_retry(
            "career_readability_fix",
            POLISH_SYSTEM_PROMPT,
            user_prompt,
            REVISE_TOOL,
            extract=lambda r: job_match.require_resume_shape(job_match._extract_tool_input(r, "submit_revised_resume", ("resume_data",))),
        )
        revised = data.get("resume_data") or {}
        required = ("name", "contact", "headline", "summary", "skills", "experience", "education")
        if any(k not in revised for k in required):
            return resume_data, info
        old_jobs, new_jobs = resume_data.get("experience") or [], revised["experience"]
        if len(new_jobs) != len(old_jobs) or any(len(a.get("bullets") or []) != len(b.get("bullets") or []) for a, b in zip(old_jobs, new_jobs)):
            return resume_data, info
        before_text, after_text = resume_text(resume_data), resume_text(revised)
        if any(term_in_text(t["term"], before_text) and not term_in_text(t["term"], after_text) for t in supported):
            print("[career.quality] edit rejected: it lost a posting keyword")
            return resume_data, info
        after = check(revised)
        if len(after) >= len(issues) or truth_count(after) > truth_count(issues):
            print("[career.quality] edit rejected: it did not reduce the problems")
            return resume_data, info
        info.update(remaining=len(after), edited=True)
        return revised, info
    except Exception as e:  # an optional polish step must never break a build
        print(f"[career.quality] skipped: {type(e).__name__}")
        return resume_data, info


def log_quality(info: dict) -> None:
    print(f"[career.quality] problems_found={info['found']} remaining={info['remaining']} edited={info['edited']}")


def ats_style_score(resume_data: dict, terms: list[dict]) -> dict:
    """What a keyword scanner (Jobscan and similar) would report: the share of ALL the posting's terms that appear on the
    resume, counting every term equally, including context wording and terms the profile does not support (an honest
    resume still leaves those off). The Job Fit grade, by contrast, weights required terms and ignores unused context
    wording; the two numbers answer different questions."""
    text = resume_text(resume_data)
    found = [t for t in terms if term_in_text(t["term"], text)]
    total = len(terms)
    return {
        "pct": round(100 * len(found) / total) if total else None,
        "found": len(found),
        "total": total,
        "missing_supported": sum(1 for t in terms if t not in found and t["support"] in SUPPORTED),
        "missing_unsupported": sum(1 for t in terms if t not in found and t["support"] not in SUPPORTED),
    }


def log_term_summary(terms: list[dict], ats: dict) -> None:
    """One server-log line per build, so a mismatch with an outside scanner can be read straight from the log: every
    posting term that was left off the resume and why. Posting terms only, never anything from the candidate's profile."""
    def names(items):
        return "; ".join(t["term"] for t in items) or "-"
    left_off = [t for t in terms if not t.get("on_resume")]
    print(
        f"[career.terms] planned={len(terms)} ats_style={ats['pct']}% "
        f"not_placed=[{names([t for t in left_off if t['support'] in SUPPORTED and t.get('kind') != 'phrase'])}] "
        f"phrases_unused=[{names([t for t in left_off if t['support'] in SUPPORTED and t.get('kind') == 'phrase'])}] "
        f"transferable=[{names([t for t in left_off if t['support'] == TRANSFERABLE])}] "
        f"not_in_profile=[{names([t for t in left_off if t['support'] not in SUPPORTED and t['support'] != TRANSFERABLE])}]"
    )


def sanitize_skills(resume_data: dict, terms: list[dict], evidence_text: str) -> tuple[dict, list[str]]:
    """The last, plain-code pass over SKILLS. A skill is removed only when it (a) is a posting term the evidence does not
    establish (support "none", including everything the candidate denied), or (b) shares no distinctive word at all with the
    candidate's evidence, so it cannot be traced to anything they said. Skills that are literal, related or transferable
    terms, and skills traceable to the evidence, stay. Returns (resume, the skills removed)."""
    # Words are compared by their first five letters, so 'resolved' traces to 'resolution' and 'handled' to 'handling': a
    # genuine skill the candidate describes in different words must not be dropped for a spelling difference.
    def stems(text):
        return {r[:5] for r in resume_quality.distinct_roots(text)}

    # Traceable means: a distinctive word of the skill appears in what the CANDIDATE said (profile and confirmed facts). Words that
    # only appear in a planned posting term do not count, or a skill like "Stakeholder Collaboration" would pass on the strength
    # of an unrelated term that happens to share the word "collaboration".
    evidence_roots = stems(evidence_text)
    keep_terms = [t for t in terms if t["support"] in SUPPORTED or t["support"] == TRANSFERABLE]
    none_terms = [t["term"] for t in terms if t["support"] == "none" and t.get("kind") != "phrase"]
    removed: list[str] = []
    lines: list[str] = []
    for line in resume_data.get("skills") or []:
        label, sep, rest = line.partition(":")
        grouped = bool(sep) and len(label) <= 40
        kept = []
        for item in _split_top_level(rest if grouped else line):
            item = _clean_item(item)
            roots = stems(item)
            is_keep_term = any(term_in_text(t["term"], item) or normalize(t["term"]) == normalize(item) for t in keep_terms)
            matches_none = any(normalize(n) == normalize(item) or (len(resume_quality.distinct_roots(n)) >= 2 and term_in_text(n, item)) for n in none_terms)
            untraceable = bool(roots) and not (roots & evidence_roots)
            if (matches_none or untraceable) and not is_keep_term:
                removed.append(item)
                continue
            kept.append(item)
        if kept:
            lines.append(f"{label.strip()}: {', '.join(kept)}" if grouped else ", ".join(kept))
    return {**resume_data, "skills": lines}, removed


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}


def _evidence_with_number_digits(evidence_text: str) -> str:
    """The evidence plus the digit form of every number it spells out ("five sections" also supplies "5"), so a writer who turns
    "five" into "5" is not mistaken for inventing a figure."""
    words = set(_WORD.findall((evidence_text or "").lower()))
    return evidence_text + " " + " ".join(str(n) for w, n in _NUMBER_WORDS.items() if w in words)


def invented_figures(text: str, evidence_text: str) -> list[str]:
    """The figures in one piece of prose that are not in the candidate's evidence (a number, amount or percentage the profile and
    confirmed facts do not contain), using the same check the quality pass uses. Names are NOT included: the name check has a
    higher false-positive risk, so names stay flagged-only."""
    if not evidence_text:
        return []
    issues = resume_quality.find_issues({"summary": text, "headline": "", "experience": []}, _evidence_with_number_digits(evidence_text), [], term_in_text, "")
    return [i["problem"] for i in issues if "figure" in i["problem"]]


def strike_unsupported_claims(resume_data: dict, unsupported_terms: list[str], evidence_text: str = "") -> tuple[dict, list[dict]]:
    """The last-resort safeguard. After the edit pass (which may be unavailable or may not fix everything), any SENTENCE that still
    (a) states a qualification the evidence does not establish (a posting term marked unsupported, which includes everything the
    candidate denied, written out or paraphrased) or (b) contains a figure that is not in the candidate's evidence is removed by
    plain code, so a flagged claim can never reach the saved or downloaded resume. Only the offending sentence goes: the rest of a
    bullet or summary stays; a bullet with nothing left is dropped; a headline phrase (split on "|") is dropped. Nothing is
    substituted. Returns (resume, what was struck, each with its reason)."""
    struck: list[dict] = []

    def reason(text: str) -> str:
        if unsupported_terms and resume_quality.find_claim_issues({"summary": text, "headline": "", "experience": []}, unsupported_terms, evidence_text):
            return "unsupported claim"
        if invented_figures(text, evidence_text):
            return "figure not in the candidate's evidence"
        return ""

    def keep(text: str, where: str) -> str:
        sentences = [x for x in resume_quality._SENTENCE_SPLIT.split(text.strip()) if x.strip()]
        kept = []
        for sentence in sentences:
            why = reason(sentence)
            if why:
                struck.append({"where": where, "text": sentence.strip(), "reason": why})
            else:
                kept.append(sentence.strip())
        return " ".join(kept)

    if not unsupported_terms and not evidence_text:
        return resume_data, struck
    out = dict(resume_data)
    if out.get("summary"):
        out["summary"] = keep(out["summary"], "summary")
    if out.get("headline"):
        parts = [x.strip() for x in str(out["headline"]).split("|")]
        kept_parts = []
        for x in parts:
            why = reason(x)
            if why:
                struck.append({"where": "headline", "text": x, "reason": why})
            else:
                kept_parts.append(x)
        out["headline"] = " | ".join(kept_parts)
    experience = []
    for job in out.get("experience") or []:
        bullets = []
        for bullet in job.get("bullets") or []:
            text = keep(str(bullet), f"bullet under \"{job.get('title', '')}\"")
            if text:
                bullets.append(text)
        experience.append({**job, "bullets": bullets})
    out["experience"] = experience
    return out, struck


def truth_notice(struck: list, removed: list, held: list | None = None, restored: list | None = None) -> dict:
    """The one line a candidate sees when statements were left out: how many, and what to do about it. The count is every sentence
    struck from the summary, headline or bullets plus every skill removed; nothing that was kept is counted. One claim is counted
    once: the same sentence struck in two places counts once, and a removed skill that a struck sentence also names counts with
    that sentence, not again. (Skills dropped only as duplicates, sentence-like entries or context wording are tidying, not
    unverified statements, and are not counted.)"""
    unique: dict[str, dict] = {}
    for i, item in enumerate(struck or []):
        text = normalize(str((item or {}).get("text", "")))
        unique.setdefault(text or f"#{i}", item)
    struck_texts = [str((item or {}).get("text", "")) for item in unique.values()]
    skills_alone = [s for s in (removed or []) if not any(term_in_text(s, text) for text in struck_texts)]
    count = len(unique) + len(set(normalize(s) for s in skills_alone))
    held_lines, seen_held = [], set()
    for h in held or []:  # the same line held in two places is one line
        key = normalize(str(h.get("text", "")))
        if key not in seen_held:
            seen_held.add(key)
            held_lines.append({"text": h.get("text", ""), "said": h.get("evidence_verb", "")})
    notice = {"count": count, "message": "", "held": held_lines, "held_message": "", "restored_message": ""}
    if count:
        noun = "statement" if count == 1 else "statements"
        notice["message"] = f"We left out {count} {noun} we couldn’t verify. Review your experience to make sure nothing important is missing."
    if held_lines:
        n = len(held_lines)
        notice["held_message"] = (f"We held {n} {'line' if n == 1 else 'lines'} out of your résumé until you confirm {'it' if n == 1 else 'them'}. "
                                  f"{'It uses' if n == 1 else 'They use'} stronger wording than you gave us, so {'it is' if n == 1 else 'they are'} not in your Word file yet. "
                                  f"To include {'it' if n == 1 else 'them'}, tell us more about what you did in the interview, then rebuild your résumé.")
    if restored:
        r = len(restored)
        notice["restored_message"] = (f"We put {r} {'line' if r == 1 else 'lines'} back to the wording you gave us, because our draft used a stronger word than you did.")
    return notice


def check_provenance(result: dict, resume: dict, profile_text: str, job_description: str, confirmed_facts: list, terms: list[dict] | None) -> dict:
    """Every bullet is compared with the saved entry of its own role, the summary and Skills with the plan (see career/provenance.py). A line the
    candidate's own history does not state is put back to their own sentence for that role, or left out, and reported in result["provenance"];
    returns the checked resume."""
    checked, report = provenance.audit_and_repair(resume, profile_text, job_description, facts_text_for(confirmed_facts), posting_title(job_description), terms)
    result["provenance"] = {**report, **provenance.notice_text(report)}
    if result["provenance"]["count"]:
        print(f"[career.truth] provenance restored={len(report['restored'])} held={len(report['held'])} skills_removed={len(report['skills_removed'])}")
    return checked


def _facts_as_resume(confirmed_facts: list) -> dict:
    return {"summary": "", "experience": [{"title": "confirmed facts", "bullets": [str(f.get("bullet_text", "")) for f in confirmed_facts or []]}]}


def check_verb_wording(result: dict, resume: dict, profile_text: str, confirmed_facts: list, answers_text: str = "") -> dict:
    """Stronger-than-evidence verbs ("Produced" for "recorded", "Led" for "helped"). The candidate's own words are the evidence: the
    profile they wrote and what they typed in the interview. A confirmed fact whose verb is already stronger than those words is
    not evidence for the stronger verb (the interview step wrote it, the candidate did not). Each resume sentence is then
    restored to the candidate's own meaning when one sentence of theirs unambiguously covers it, or held out of the resume
    (and out of the Word file) until the candidate confirms it. Sets verb_review (what is still flagged: nothing, after this),
    fact_verb_review, verbs_restored and lines_held on the result; returns the checked resume."""
    own_words = profile_text + "\n" + answers_text
    flagged_facts = resume_quality.verb_upgrades(_facts_as_resume(confirmed_facts), own_words)
    flagged_texts = {f["text"] for f in flagged_facts}
    trusted_facts = [str(f.get("bullet_text", "")) for f in confirmed_facts or [] if str(f.get("bullet_text", "")).strip() not in flagged_texts]
    trusted = own_words + "\n" + "\n".join(trusted_facts)
    resume, restored, held = resume_quality.resolve_verb_upgrades(resume, trusted)
    result["fact_verb_review"] = flagged_facts
    result["verbs_restored"] = restored
    result["lines_held"] = held
    result["verb_review"] = resume_quality.verb_upgrades(resume, trusted)
    return resume


def build_checked_resume(profile_text: str, job_description: str, confirmed_facts: list, name: str, contact: str, denials: list[dict] | None = None, answers_text: str = "", saved_terms: list[dict] | None = None) -> dict:
    denials = denials or []
    # A confirmed fact that says again what the candidate denied is NOT silently used, and the denial is not silently dropped:
    # the fact is held back and the conflict is reported so the candidate can clarify.
    conflicts = resume_quality.find_conflicts(denials, confirmed_facts)
    held = {c["fact"] for c in conflicts}
    confirmed_facts = [f for f in confirmed_facts or [] if str(f.get("bullet_text", "")) not in held]
    facts_text = facts_text_for(confirmed_facts)

    try:
        if saved_terms:
            # the keyword step already asked the AI; its plan is re-checked against today's evidence and denials, with no second call
            terms = reguard_saved_terms(saved_terms, profile_text, facts_text, job_description, denials)
            print(f"[career.terms] reused the keyword-step plan ({len(terms)} terms); no planning call")
        else:
            terms = plan_terms(profile_text, facts_text, job_description, denials)
    except JobMatchError:
        print("[career.terms] planning failed; building without a term plan")
        terms = None  # fall back to the plain one-call build, no report

    result = job_match.build_tailored_resume(
        profile_text, job_description, confirmed_facts, name, contact, term_plan=terms, denials=denials
    )
    evidence_text = profile_text + "\n" + facts_text
    result["answer_conflicts"] = conflicts
    if not terms:
        resume, quality = improve_readability(dedupe_skills(result["resume_data"]), evidence_text, [])
        resume, removed = sanitize_skills(resume, [], evidence_text)
        result["resume_data"] = resume
        result["quality"] = quality
        result["skills_removed"] = removed
        result["claims_struck"] = []
        resume = check_verb_wording(result, resume, profile_text, confirmed_facts, answers_text)
        resume = check_provenance(result, resume, profile_text, job_description, confirmed_facts, None)
        result["resume_data"] = resume
        result["truth_notice"] = {**truth_notice([], removed, result["lines_held"], result["verbs_restored"]), "provenance": result["provenance"]}
        result["claim_review"] = []
        log_quality(quality)
        result["term_report"] = []
        return result

    # Context phrases ("sales setting", "difficult customers") are never skills:
    # the code removes them from SKILLS even if the model put them there.
    wording = {normalize(t["term"]) for t in terms if t.get("kind") == "phrase"}
    resume = dedupe_skills(result["resume_data"], wording)
    check_placement(resume, terms)
    # Only real skills are forced in by the fix-up; phrases are used only where natural.
    missing = [t for t in terms if t["support"] in SUPPORTED and not t["on_resume"] and t.get("kind") != "phrase"]
    if missing:
        try:
            revised = add_missing_terms(resume, missing)
        except JobMatchError:
            revised = None
        if revised is None:
            print(f"[career.terms] fix-up unusable; {len(missing)} supported term(s) left unplaced")
        if revised:
            resume = dedupe_skills({**resume, **revised}, wording)
            check_placement(resume, terms)
    unsupported = [t["term"] for t in terms if t["support"] == "none" and t.get("kind") != "phrase"]
    # Never state the target: a sentence that says the candidate IS the posting's job title (when their evidence never says so) is unsupported.
    title = posting_title(job_description)
    if title and not term_in_text(title, evidence_text) and title not in unsupported:
        unsupported.append(title)
    resume, quality = improve_readability(resume, evidence_text, terms, unsupported)
    resume, removed = sanitize_skills(resume, terms, evidence_text)
    resume, struck = strike_unsupported_claims(resume, unsupported, evidence_text)
    check_placement(resume, terms)
    # what the checks could not fix is reported, never hidden
    result["claim_review"] = resume_quality.find_claim_issues(resume, unsupported, evidence_text)
    result["skills_removed"] = removed
    result["claims_struck"] = struck
    resume = check_verb_wording(result, resume, profile_text, confirmed_facts, answers_text)
    resume = check_provenance(result, resume, profile_text, job_description, confirmed_facts, terms)
    check_placement(resume, terms)  # statuses and the score follow the resume as finally written
    result["truth_notice"] = {**truth_notice(struck, removed, result["lines_held"], result["verbs_restored"]), "provenance": result["provenance"]}
    if removed or struck or result["claim_review"] or conflicts:
        print(f"[career.truth] skills_removed={len(removed)} sentences_struck={len(struck)} unsupported_claims_left={len(result['claim_review'])} answer_conflicts={len(conflicts)}")
    result["quality"] = quality
    log_quality(quality)
    result["resume_data"] = resume
    result["ats_match"] = ats_style_score(resume, terms)
    log_term_summary(terms, result["ats_match"])
    met_groups = {t["alternatives_group"] for t in terms if t.get("alternatives_group") and t["support"] in SUPPORTED}
    result["term_report"] = [
        {"term": t["term"], "kind": t.get("kind", "skill"), "importance": t["importance"], "support": t["support"],
         "evidence": t["evidence"],
         # the posting accepts any ONE of a group: an unmet member of a group another member already meets is not a gap
         "status": "alternative_met" if t.get("alternatives_group") in met_groups and t["support"] not in SUPPORTED else _status(t)}
        for t in terms
    ]
    return result
