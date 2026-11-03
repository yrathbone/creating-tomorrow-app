"""Quality checks on a finished, job-targeted resume: is it TRUE to the candidate's profile, and does it READ like a person wrote it?

The AI writes the resume; these checks do not trust it. They are plain code (no AI), so they are fast, free and testable. Each
problem found is an "issue" that the pipeline hands to one small, targeted edit pass (term_pipeline.improve_readability), which
is accepted only if it removes problems without losing a keyword or adding a fact.

Truth checks (the resume may not introduce what the profile does not contain):
  - a number, amount or percentage in the summary or a bullet that is not in the profile or the confirmed facts
    ("10+ years" is allowed while it does not exceed the span from the earliest year in the profile to today);
  - a capitalised name or acronym mid-sentence (a tool, employer, product) that is in neither the profile nor a posting term the
    candidate's evidence supports.
Readability checks (limits a person can feel when reading):
  - a summary of more than 4 sentences, or a summary sentence over 25 words;
  - a bullet over 30 words;
  - more than 3 posting terms packed into one summary sentence (4 for a bullet), which reads like keyword stuffing;
  - two or more dashes in one sentence (the "- from discovery through implementation -" run-on pattern);
  - the same long word three times in one sentence.
"""
import datetime
import re

MAX_SUMMARY_SENTENCES = 4
MAX_SUMMARY_SENTENCE_WORDS = 25
MAX_BULLET_WORDS = 30
MAX_TERMS_PER_SUMMARY_SENTENCE = 3
MAX_TERMS_PER_BULLET = 4

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\$?(\d[\d,]*(?:\.\d+)?)(\+?)(\s*(?:years?|yrs?)\b)?", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_YEAR = re.compile(r"\b(19[6-9]\d|20[0-4]\d)\b")
_DASHES = re.compile(r"—|–|(?<=\s)-(?=\s)")
_MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}


def _stem(word: str) -> str:
    word = word.lower()
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _token_set(text: str) -> set[str]:
    return {_stem(w) for w in _TOKEN.findall(text or "")}


def _number_key(raw: str) -> str:
    digits = raw.replace(",", "")
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    return digits


def _numbers(text: str) -> list[tuple[str, bool, bool]]:
    """(normalised number, followed by '+', followed by 'years') for each number in the text."""
    return [(_number_key(m.group(1)), bool(m.group(2)), bool(m.group(3))) for m in _NUMBER.finditer(text or "")]


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def prose_units(resume: dict) -> list[dict]:
    """Every piece of resume prose with a stable address the edit pass can be pointed at: summary sentences and experience bullets."""
    units = []
    summary = (resume.get("summary") or "").strip()
    sentences = [s for s in _SENTENCE_SPLIT.split(summary) if s.strip()]
    for i, sentence in enumerate(sentences):
        units.append({"where": "summary", "kind": "summary", "text": sentence.strip(), "index": i, "count": len(sentences)})
    for job in resume.get("experience") or []:
        for bullet in job.get("bullets") or []:
            units.append({"where": f"bullet under \"{job.get('title', '')}\"", "kind": "bullet", "text": str(bullet), "index": 0, "count": 1})
    return units


def find_issues(resume: dict, evidence_text: str, term_names: list[str], present, extra_allowed_text: str = "", today_year: int | None = None) -> list[dict]:
    """Every truth or readability problem in the resume's prose, as [{where, problem, text}].

    evidence_text:       the candidate's Career Profile plus confirmed facts (the only source of truth).
    term_names:          the posting terms the candidate's evidence supports (for the keyword-stuffing check).
    present:             term_in_text(term, text), injected so this module stays free of the pipeline's imports.
    extra_allowed_text:  text whose names are fine to use (the supported posting terms and their evidence)."""
    issues: list[dict] = []
    year = today_year or datetime.date.today().year
    evidence_numbers = {n for n, _, _ in _numbers(evidence_text)}
    evidence_tokens = _token_set(evidence_text) | _token_set(extra_allowed_text) | _MONTHS
    years_seen = [int(y) for y in _YEAR.findall(evidence_text or "")]
    max_years = (year - min(years_seen)) if years_seen else None

    units = prose_units(resume)
    summary_count = units[0]["count"] if units and units[0]["kind"] == "summary" else 0
    if summary_count > MAX_SUMMARY_SENTENCES:
        issues.append({"where": "summary", "problem": f"the summary has {summary_count} sentences; keep it to {MAX_SUMMARY_SENTENCES} or fewer", "text": resume.get("summary", "")})

    # a number elsewhere on the resume (headline) must be true as well
    texts = [(u["where"], u["text"], u["kind"]) for u in units]
    if resume.get("headline"):
        texts.append(("headline", resume["headline"], "headline"))

    for where, text, kind in texts:
        for number, plus, is_years in _numbers(text):
            if is_years and max_years is not None:
                try:
                    if float(number) <= max_years:
                        continue
                except ValueError:
                    pass
            if number not in evidence_numbers:
                issues.append({"where": where, "problem": f"the figure \"{number}\" is not in the candidate's profile; remove it or use only a figure from the profile", "text": text})

        if kind == "headline":
            continue  # a headline is Title Case throughout; only its figures are checked

        words = _TOKEN.findall(text)
        if kind in ("summary", "bullet"):
            for match in _TOKEN.finditer(text):
                word = match.group(0)
                before = text[: match.start()].rstrip()
                # the first word of a sentence or clause is capitalised for grammar, not because it is a name
                if not before or before[-1] in ".!?:;—–-(" or not word[:1].isupper():
                    continue
                if _stem(word) not in evidence_tokens and not word.isdigit():
                    issues.append({"where": where, "problem": f"\"{word}\" is not in the candidate's profile (a name, tool or product they never mentioned); remove it", "text": text})
                    break

        count = _words(text)
        if kind == "summary" and count > MAX_SUMMARY_SENTENCE_WORDS:
            issues.append({"where": where, "problem": f"this summary sentence is {count} words; split or tighten it to {MAX_SUMMARY_SENTENCE_WORDS} or fewer", "text": text})
        if kind == "bullet" and count > MAX_BULLET_WORDS:
            issues.append({"where": where, "problem": f"this bullet is {count} words; tighten it to {MAX_BULLET_WORDS} or fewer", "text": text})
        limit = MAX_TERMS_PER_SUMMARY_SENTENCE if kind == "summary" else MAX_TERMS_PER_BULLET
        stacked = [t for t in term_names if present(t, text)]
        if len(stacked) > limit:
            issues.append({"where": where, "problem": f"{len(stacked)} posting keywords are packed into one {kind == 'summary' and 'sentence' or 'bullet'} ({', '.join(stacked[:6])}); spread them out so it reads naturally, keeping each keyword somewhere", "text": text})
        if len(_DASHES.findall(text)) >= 2:
            issues.append({"where": where, "problem": "two or more dashes in one sentence read as a run-on; use shorter sentences", "text": text})
        long_words: dict[str, int] = {}
        for w in words:
            if len(w) >= 6:
                long_words[_stem(w)] = long_words.get(_stem(w), 0) + 1
        repeated = [w for w, n in long_words.items() if n >= 3]
        if repeated:
            issues.append({"where": where, "problem": f"the word \"{repeated[0]}\" is repeated three times in one sentence", "text": text})
    return issues


def drop_unsourced_bullets(resume: dict, sources: list[dict]) -> tuple[dict, list[str]]:
    """A role the candidate gave no description (and no skills) for may not carry bullets: any the AI wrote are invented duties.

    sources: [{"title", "organization", "has_source"}] for each profile role. A resume role is matched by its title and by the
    organization named in its subtitle; a role that matches nothing is left alone. Returns a copy of the resume with those bullets
    emptied, and the titles of the roles that were emptied (for the log). Plain code, no AI."""
    emptied: list[str] = []
    experience = []
    for job in resume.get("experience") or []:
        title = str(job.get("title", "")).strip().lower()
        subtitle = str(job.get("subtitle", "")).lower()
        match = [s for s in sources if str(s.get("title", "")).strip().lower() == title and str(s.get("organization", "")).strip().lower() in subtitle]
        if match and not any(s.get("has_source") for s in match) and job.get("bullets"):
            emptied.append(str(job.get("title", "")))
            job = {**job, "bullets": []}
        experience.append(job)
    return {**resume, "experience": experience}, emptied


# ---------------------------------------------------------------------------------------------------------------------
# Evidence, denials and unsupported claims (Finding 2, Phase 02 Checkpoint B).
#
# Principle: discover the value, preserve the truth, communicate the potential. A posting is a source of RELEVANCE, never of
# facts about the candidate. These checks are plain code (no AI). They trace a claim back to the candidate's own evidence,
# they respect an explicit "No" with its SCOPE (a denied specialised activity is not a denied adjacent one), and they never
# treat a skipped question as a "Yes". Their limits are listed in docs/TRUTHFULNESS.md.
# ---------------------------------------------------------------------------------------------------------------------

_SCOPE_CUT = re.compile(r"\b(?:beyond|other than|as opposed to|rather than|instead of|besides|outside of|outside)\b[^.;?)]*", re.I)

# words that carry no skill or activity on their own (question wording, glue words, generic filler)
_STOP_WORDS = set("""a an and are as at be been but by can could did do does for from had has have how i if in into is it its may me my
of on or our so than that the their them then there these they this those to up us was we were what when where which who why will
with would you your yours ever any some more most other such not no yes also very just like own about over under per via
skill skills experience experienced ability able knowledge work working worked use used using familiar strong good basic simple
including include includes related relevant role roles job jobs position years year day days time times level levels type types
required preferred mentioned partial missing
directly previously currently daily weekly regularly often helped help provide provided provides provide supported support
""".split())


def _root(word: str) -> str:
    """A light stem: 'handled', 'handling' and 'handle' share one root; 'customers' and 'customer' too. Deliberately simple."""
    w = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)]
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


_STOP_ROOTS = {_root(w) for w in _STOP_WORDS} | _STOP_WORDS


def distinct_roots(text: str) -> set[str]:
    """The roots of the words in a text that say something (glue words, filler and one-letter tokens are dropped)."""
    return {r for r in (_root(w) for w in _TOKEN.findall((text or "").lower())) if len(r) > 1 and r not in _STOP_ROOTS}


def _scope_text(text: str) -> str:
    """The part of a question the candidate was actually answering: what follows 'beyond ...', 'as opposed to ...' is the
    contrast, not the subject ('video editing (beyond simple screen recording)' does not deny screen recording)."""
    return _SCOPE_CUT.sub(" ", text or "")


def denials_from_history(qa_history) -> list[dict]:
    """The gap-interview questions the candidate explicitly answered NO. A skipped or unanswered question is not here and is
    never read as a yes either; detail (free text) answers are not denials."""
    denials = []
    for entry in qa_history or []:
        if not isinstance(entry, dict) or str(entry.get("type", "yes_no")) == "detail":
            continue
        if str(entry.get("answer", "")).strip().lower() != "no":
            continue
        question = str(entry.get("question", "")).strip()
        if question:
            denials.append({"question": question, "category": str(entry.get("category", "") or "")})
    return denials


def denied_by(term: str, denials: list[dict]) -> dict | None:
    """The denial that covers a posting term, or None. A term is covered only when EVERY distinctive word of a multi-word term
    sits inside what the candidate said no to, so 'video editing' is covered by a no to 'video editing software' while
    'collaboration' or 'classroom collaboration' is not. One-word terms are never covered here (the planner judges those)."""
    roots = distinct_roots(term)
    if len(roots) < 2:
        return None
    for denial in denials or []:
        # The gap the question was about ("Video editing (preferred)", "ADDIE or SAM") is the subject of the denial. Only when
        # a question carries no gap name do its own words stand in for it. Matching every word of the whole question would make
        # a no to "ADDIE or SAM instructional design models" wrongly deny the general skill "instructional design".
        subject = distinct_roots(_scope_text(denial.get("category", "")))
        if not subject:
            subject = distinct_roots(_scope_text(denial["question"]))
        if roots <= subject:
            return denial
    return None


def find_conflicts(denials: list[dict], confirmed_facts: list) -> list[dict]:
    """A confirmed fact that says again what the candidate denied (three or more distinctive words in common with the denied
    question). Neither statement is silently overridden: the conflict is reported so the candidate can clarify."""
    conflicts = []
    for fact in confirmed_facts or []:
        text = str((fact or {}).get("bullet_text", ""))
        fact_roots = distinct_roots(text)
        for denial in denials or []:
            shared = fact_roots & distinct_roots(_scope_text(denial["question"]))
            if len(shared) >= 3:
                conflicts.append({"fact": text, "denied_question": denial["question"], "shared": sorted(shared)})
                break
    return conflicts


def _claim_units(resume: dict) -> list[tuple[str, str]]:
    units = [("summary", s["text"]) for s in prose_units(resume) if s["kind"] == "summary"]
    if resume.get("headline"):
        units.append(("headline", resume["headline"]))
    for job in resume.get("experience") or []:
        for bullet in job.get("bullets") or []:
            units.append((f"bullet under \"{job.get('title', '')}\"", str(bullet)))
    return units


def find_claim_issues(resume: dict, unsupported_terms: list[str]) -> list[dict]:
    """Every sentence that states a qualification the candidate's evidence does not establish: a posting term the planner marked
    'none' (or the candidate denied) appearing in the summary, headline or a bullet. Only multi-word terms are checked, so a
    legitimate common word is never flagged. Returns [{where, problem, text}] in the shape find_issues uses."""
    issues = []
    for where, text in _claim_units(resume):
        normalized = " ".join(_root(w) for w in _TOKEN.findall(text.lower()))
        for term in unsupported_terms:
            words = [_root(w) for w in _TOKEN.findall(term.lower())]
            if len(distinct_roots(term)) >= 2 and f" {' '.join(words)} " in f" {normalized} ":
                issues.append({"where": where, "problem": f"unsupported claim: \"{term}\" is not established by the candidate's evidence; remove it, or say only what the evidence says (do not swap in another unsupported claim)", "text": text})
                break
    return issues
