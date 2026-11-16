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
import copy
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


# "K-12" (also "K12", "pre-K-12") names a school range, not a figure. Reading its "12" as a number wrongly flagged, and the strike then
# removed, a true headline phrase and summary sentence in the live Daniel Reyes rerun (2026-11-03).
_SCHOOL_RANGE = re.compile(r"\b(?:pre-?)?K\s*[-–—]?\s*12\b", re.I)


def _numbers(text: str) -> list[tuple[str, bool, bool]]:
    """(normalised number, followed by '+', followed by 'years') for each number in the text (a school range such as K-12 is not a number)."""
    text = _SCHOOL_RANGE.sub(" ", text or "")
    return [(_number_key(m.group(1)), bool(m.group(2)), bool(m.group(3))) for m in _NUMBER.finditer(text)]


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
        # The term must also make up at least half of the subject's distinctive words. A long gap label ("ADDIE or SAM instructional
        # design models") describes the TYPE of thing denied; a general skill that merely sits inside it ("instructional design") is
        # not what was denied. In the live Daniel rerun this over-reach removed the genuine skill "instructional design".
        if roots <= subject and len(roots) * 2 >= len(subject):
            return denial
    return None


def find_conflicts(denials: list[dict], confirmed_facts: list) -> list[dict]:
    """A confirmed fact that says again what the candidate denied. Neither statement is silently overridden: the conflict is
    reported so the candidate can clarify.

    The comparison is against the SUBJECT of the denial (the gap it was named for, such as "Video editing"), the same scope
    denied_by uses, and needs two shared distinctive words (one when the subject has only one). Comparing a fact with the whole
    question wrongly flagged a true fact about assessments tracked in Google Sheets as conflicting with a No about "other software
    to build digital learning content", because they shared the incidental words "based", "google" and "learn". When a denial has
    no gap name, its question stands in for it and three shared words are needed, as before."""
    conflicts = []
    for fact in confirmed_facts or []:
        text = str((fact or {}).get("bullet_text", ""))
        fact_roots = distinct_roots(text)
        for denial in denials or []:
            subject = distinct_roots(_scope_text(denial.get("category", "")))
            need = min(2, len(subject)) if subject else 3
            if not subject:
                subject = distinct_roots(_scope_text(denial["question"]))
            shared = fact_roots & subject
            if shared and len(shared) >= need:
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


def _stems(text: str) -> set[str]:
    """Distinctive words as five-letter stems, so 'regulated'/'regulatory' and 'account'/'accounts' compare equal."""
    return {r[:5] for r in distinct_roots(text)}


def sentence_claims_term(sentence: str, term: str, evidence_stems: set[str]) -> bool:
    """Does this sentence state the unsupported term? Two ways, both plain code:
    (1) the term's own words appear in a row (the exact phrase, case, plural and hyphen insensitive); or
    (2) a PARAPHRASE: the sentence uses most of the term's distinctive words (at least two, and two thirds of them) and at least one
        of those shared words is NOT in the candidate's own evidence. A sentence made of the candidate's own words is never flagged
        by (2), so genuine adjacent experience that happens to share a word with a denied term is left alone."""
    words = [_root(w) for w in _TOKEN.findall(term.lower())]
    normalized = " ".join(_root(w) for w in _TOKEN.findall(sentence.lower()))
    if len(distinct_roots(term)) >= 2 and f" {' '.join(words)} " in f" {normalized} ":
        return True
    term_stems = _stems(term)
    if len(term_stems) < 2:
        return False
    overlap = term_stems & _stems(sentence)
    need = max(2, -(-2 * len(term_stems) // 3))
    return len(overlap) >= need and bool(overlap - evidence_stems)


def find_claim_issues(resume: dict, unsupported_terms: list[str], evidence_text: str = "") -> list[dict]:
    """Every sentence that states a qualification the candidate's evidence does not establish: a posting term the planner marked
    'none' (or the candidate denied), written out or paraphrased, in the summary, headline or a bullet. Only multi-word terms are
    checked, so a legitimate common word is never flagged. Returns [{where, problem, text}] in the shape find_issues uses."""
    issues = []
    evidence_stems = _stems(evidence_text)
    for where, text in _claim_units(resume):
        for term in unsupported_terms:
            if sentence_claims_term(text, term, evidence_stems):
                issues.append({"where": where, "problem": f"unsupported claim: \"{term}\" is not established by the candidate's evidence; remove it, or say only what the evidence says (do not swap in another unsupported claim)", "text": text})
                break
    return issues


# ---- verbs the writer must not upgrade ---------------------------------------------------------------------------------------
# A stronger verb the candidate's own words never use, next to a weaker verb they DID use ("produced" when they said "recorded"),
# changes what they did. Reported for review, never silently rewritten (a swap would often break the sentence).
_STRONG_VERBS = {
    "produced": ("produc",), "managed": ("manag",), "led": ("led", "lead"), "directed": ("direct",),
    "oversaw": ("oversaw", "oversee", "oversight"), "owned": ("own",), "spearheaded": ("spearhead",),
    # responsibility and relationship verbs: doing the work, or supervising / guiding / mentoring people, is more than helping or working beside them
    "performed": ("perform",), "executed": ("execut",), "supervised": ("supervis",), "guided": ("guid",), "mentored": ("mentor",),
    "coordinated": ("coordinat",), "administered": ("administ",),
}
_WEAK_STEMS = {
    "produced": ("record", "film"),
    "managed": ("assist", "help", "support", "contribut"),
    "led": ("assist", "help", "support", "contribut"),
    "directed": ("assist", "help", "support", "contribut"),
    "oversaw": ("assist", "help", "support", "contribut"),
    "owned": ("assist", "help", "support", "contribut"),
    "spearheaded": ("assist", "help", "support", "contribut"),
    "performed": ("assist", "help", "support", "contribut", "observ", "shadow", "particip"),
    "executed": ("assist", "help", "support", "contribut", "observ", "shadow", "particip"),
    "administered": ("assist", "help", "support", "contribut"),
    "coordinated": ("assist", "help", "support", "contribut"),
    "supervised": ("assist", "help", "support", "contribut", "coordinat", "collaborat", "alongside"),
    "guided": ("assist", "help", "support", "contribut", "coordinat", "collaborat", "alongside"),
    "mentored": ("assist", "help", "support", "contribut", "coordinat", "collaborat", "alongside"),
}
_WORD = re.compile(r"[a-z][a-z'-]*")


def verb_upgrades(resume_data: dict, evidence_text: str) -> list[dict]:
    """Sentences that use a strong verb the evidence never uses while the evidence does use a weaker verb for the same kind of work."""
    evidence_words = set(_WORD.findall(str(evidence_text or "").lower()))

    def established(strong: str) -> bool:
        stems = _STRONG_VERBS[strong]
        return any((w == s) if s == "led" else w.startswith(s) for w in evidence_words for s in stems)

    def weaker_used(strong: str) -> str:
        for stem in _WEAK_STEMS[strong]:
            for w in sorted(evidence_words):
                if w.startswith(stem):
                    return w
        return ""

    found: list[dict] = []
    evidence_sentences = _evidence_sentences(evidence_text)

    def weaker_for_activity(sentence: str, strong: str) -> str:
        """The strong verb IS used somewhere in the evidence, but the evidence sentences about THIS activity (they share its numbers and at
        least two of its words) only use a weaker verb: "Managed file testing" when the candidate "assisted with file testing" and managed
        something else. Returns that weaker verb, or "" when the activity is not clearly described or the strong verb is used for it."""
        numbers = {n[0] for n in _numbers(sentence)}
        own_roots = {r[:4] for r in distinct_roots(sentence) - distinct_roots(strong)}
        about, weak = [], ""
        for candidate in evidence_sentences:
            cand_words = _WORD.findall(candidate.lower())
            if not numbers <= {n[0] for n in _numbers(candidate)} or len(own_roots & {r[:4] for r in distinct_roots(candidate)}) < 2:
                continue
            about.append(candidate)
            if any((w == s) if s == "led" else w.startswith(s) for w in cand_words for s in _STRONG_VERBS[strong]):
                return ""  # the evidence uses the strong verb for this very activity
            weak = weak or next((w for w in cand_words if any(w.startswith(x) for x in _WEAK_STEMS[strong])), "")
        return weak if about else ""

    def check(text, where):
        for sentence in [x for x in _SENTENCE_SPLIT.split(str(text or "").strip()) if x.strip()]:
            words = set(_WORD.findall(sentence.lower()))
            for strong in _STRONG_VERBS:
                if strong in words:
                    weak = weaker_used(strong) if not established(strong) else weaker_for_activity(sentence, strong)
                    if weak:
                        found.append({"where": where, "text": sentence.strip(), "written": strong, "evidence_verb": weak,
                                      "problem": f"\"{strong}\" is stronger than the candidate's own wording (\"{weak}\"); use their verb or confirm it"})

    check(resume_data.get("summary"), "summary")
    for job in resume_data.get("experience") or []:
        for bullet in job.get("bullets") or []:
            check(bullet, f"bullet under \"{job.get('title', '')}\"")
    return found


# ---- restoring or holding an upgraded verb ------------------------------------------------------------------------------------
# One verb can stand in for another only when both read the same way in the sentence ("Produced 60 videos" / "Recorded 60 videos").
_INTERCHANGEABLE = {("produced", "recorded"), ("produced", "filmed")}
_HELD_SENTENCE_MAX_WORDS = 25


def candidate_answers_text(qa_history) -> str:
    """What the candidate typed in the interview (detail answers). Yes/no answers and skips say nothing about wording, and the
    questions are the tool's, not the candidate's."""
    out = []
    for entry in qa_history or []:
        if isinstance(entry, dict) and str(entry.get("type", "yes_no")) == "detail":
            answer = str(entry.get("answer", "") or "").strip()
            if answer and answer.lower() != "skip":
                out.append(answer)
    return "\n".join(out)


def _evidence_sentences(text: str) -> list[str]:
    sentences = []
    for line in str(text or "").split("\n"):
        line = re.sub(r"^\s*[-*\u2022]\s*", "", line).strip()
        sentences += [s.strip() for s in _SENTENCE_SPLIT.split(line) if s.strip()]
    return sentences


def _same_case(word: str, model: str) -> str:
    return word.capitalize() if model[:1].isupper() else word


def resolve_verb_upgrades(resume_data: dict, trusted_evidence: str) -> tuple[dict, list[dict], list[dict]]:
    """For each sentence that uses a stronger verb than the evidence does (verb_upgrades):
      - RESTORE it when ONE evidence sentence unambiguously describes the same activity (it has the weaker verb, every number of
        the line, and at least two of its other words): the verb is swapped when the two read the same way, otherwise the line is
        replaced by the candidate's own short sentence. Nothing else about the line is guessed.
      - HOLD it out of the résumé when no single such evidence sentence exists, so unverified wording is never presented as
        verified. A held line is kept in the returned list (word for word) so the candidate can confirm or correct it.
    Returns (resume, restored, held). Stronger wording the evidence supports is never touched."""
    evidence = _evidence_sentences(trusted_evidence)
    restored: list[dict] = []
    held: list[dict] = []

    def matches(sentence: str, strong: str) -> list[str]:
        numbers = {n[0] for n in _numbers(sentence)}
        own_roots = {r[:4] for r in distinct_roots(sentence) - distinct_roots(strong)}  # four letters, so plan / planning / planned agree
        found = []
        for candidate in evidence:
            words = _WORD.findall(candidate.lower())
            if not any(w.startswith(stem) for w in words for stem in _WEAK_STEMS[strong]):
                continue
            if not numbers <= {n[0] for n in _numbers(candidate)}:
                continue
            if len(own_roots & {r[:4] for r in distinct_roots(candidate)}) < 2:
                continue
            if candidate not in found:
                found.append(candidate)
        return found

    def fix(sentence: str, where: str) -> str:
        current = sentence
        for _ in range(3):
            flags = verb_upgrades({"summary": current, "experience": []}, trusted_evidence)
            if not flags:
                return current
            strong = flags[0]["written"]
            found = matches(current, strong)

            def weak_in(sentence: str) -> str:
                return next((w for w in _WORD.findall(sentence.lower()) if any(w.startswith(x) for x in _WEAK_STEMS[strong])), "")

            same_shape = next((weak_in(f) for f in found if (strong, weak_in(f)) in _INTERCHANGEABLE), "")
            if same_shape:  # the evidence has the weaker verb on the same activity: only the one word changes
                changed = re.sub(rf"\b{strong}\b", lambda m: _same_case(same_shape, m.group(0)), current, count=1, flags=re.I)
                basis = f"\"{strong}\" restored to the candidate's own \"{same_shape}\""
            elif len(found) == 1 and _words(found[0]) <= _HELD_SENTENCE_MAX_WORDS and weak_in(" ".join(_WORD.findall(found[0].lower())[:1])):
                changed = found[0].rstrip(" .") + "."
                basis = "replaced by the candidate's own sentence"
            else:
                held.append({"where": where, "text": sentence.strip(), "written": strong, "evidence_verb": flags[0]["evidence_verb"],
                             "problem": "no single sentence in the candidate's own words describes this activity safely; held for confirmation"})
                return ""
            restored.append({"where": where, "before": current.strip(), "after": changed.strip(), "basis": basis})
            current = changed
        held.append({"where": where, "text": sentence.strip(), "written": "", "evidence_verb": "", "problem": "could not be restored safely; held for confirmation"})
        return ""

    def keep(text: str, where: str) -> str:
        sentences = [x for x in _SENTENCE_SPLIT.split(str(text or "").strip()) if x.strip()]
        return " ".join(s for s in (fix(x.strip(), where) for x in sentences) if s)

    out = dict(resume_data)
    if out.get("summary"):
        out["summary"] = keep(out["summary"], "summary")
    experience = []
    for job in out.get("experience") or []:
        bullets = []
        for bullet in job.get("bullets") or []:
            text = keep(str(bullet), f"bullet under \"{job.get('title', '')}\"")
            if text:
                bullets.append(text)
        experience.append({**job, "bullets": bullets})
    out["experience"] = experience
    return out, restored, held


# ---------------------------------------------------------------------------------------------------------------------------------
# General-profile truthfulness checker (C-52 Step A; revised 2026-11-14 after Data's independent review).
# Deterministic: no AI, no paid call, no database. It never modifies its input. It is NOT wired into generation, download or approval.
#
# Classifications, each with a location, a source reference where one exists, and an explanation:
#   SUPPORTED   established by saved member information (saved skill, held title, saved employer, dates, school, credential)
#   DERIVED     supported by a specific source sentence through an explicit rule (DERIVATION_RULES, TITLE_FORMS)
#   UNSUPPORTED insufficient evidence: must not appear as an established fact, qualification, amount or scope
#   UNCERTAIN   partly supported, or a precision the saved data does not give (e.g. a month when only a year is saved): suggest it
#               to the member for confirmation; never insert it automatically
#
# Limits: word lists and token matching are deterministic signals, not semantic truth. Every UNCERTAIN and UNSUPPORTED finding must be
# resolved by the member (confirm, edit or remove) before approval or download (see Step C design). Absence of a finding is not proof.
#
# Facts (plain data built by the caller from saved career data):
#   {"roles": [{"id", "title", "organization", "years": [int],
#               "start": (year, month|None) and "end": (year, month|None) or "present"   (optional; month only if saved),
#               "text": "description, bullets and tied skills for the role"}],
#    "education": [{"school", "degree", "text"}],
#    "skills": [str]}
# Without start/end, only years are known: a generated month is then UNCERTAIN, never assumed or accepted.
# ---------------------------------------------------------------------------------------------------------------------------------

SUPPORTED = "SUPPORTED"
DERIVED = "DERIVED"
UNSUPPORTED = "UNSUPPORTED"
UNCERTAIN = "UNCERTAIN"
_RANK = {SUPPORTED: 0, DERIVED: 0, UNCERTAIN: 1, UNSUPPORTED: 2}

# Explicit derivation rule: a skill label is DERIVED only if one source sentence has a verb stem AND a process-object stem.
DERIVATION_RULES = [
    {"label": "Process Improvement", "verbs": ("improv", "streamlin", "refin", "enhanc"),
     "objects": ("checklist", "process", "procedure", "workflow", "template", "tracker", "documentation", "routine", "practice", "system")},
    # Approved 2026-11-15 (Data). The verb and object must be in the same saved statement. A statement that is hypothetical,
    # negated or planned never supports the skill. This is DERIVED, never SUPPORTED, and it promotes no title or credential.
    {"label": "Scheduling", "verbs": ("schedul",), "objects": ("rota", "shift", "roster", "timetabl"), "unit": "statement",
     "reject": ("not", "no", "never", "didn", "don", "without", "cannot", "unable", "nor", "would", "could", "might", "may", "will",
                "should", "plan", "planned", "planning", "hope", "hoping", "aim", "aiming", "want", "wanted", "if", "seeking",
                "learn", "learning")},
]
# A held title "X Coordinator" supports the skill "X Coordination": the same activity, named as a skill.
TITLE_FORMS = {"coordinator": "coordination", "manager": "management", "administrator": "administration", "analyst": "analysis"}

ROLE_NOUNS = {"coordinator", "manager", "analyst", "specialist", "director", "engineer", "officer", "lead", "assistant",
              "administrator", "representative", "supervisor", "consultant", "technician", "associate", "developer", "advisor", "chief"}
CREDENTIAL_UPGRADES = ("certified", "licensed", "accredited")
CREDENTIAL_TYPES = ("certificate", "certification", "diploma", "degree", "associate", "bachelor", "master", "doctorate")
SCOPE_WORDS = ("administrative", "operations", "leadership", "managed", "led", "oversaw", "supervised", "directed")
BULLET_SCOPE_WORDS = SCOPE_WORDS + ("budget", "owned", "owner", "headcount")
SOFT_CLAIM_PATTERNS = (r"dependable", r"reliable", r"fast-paced", r"detail-driven", r"results-driven", r"hard-working",
                       r"highly motivated", r"track record", r"proven", r"passionate", r"dynamic")
_STOP = {"a", "an", "the", "and", "of", "for", "to", "in", "with", "on", "at", "by", "from", "or", "as", "is", "was", "be", "that",
         "this", "it", "its", "their", "his", "her", "who", "while", "across", "through", "into", "over", "per", "about", "such",
         "professional", "experience", "skilled", "known", "experienced", "background", "role", "roles", "work",
         "working", "service", "oriented", "focused", "driven", "fast", "paced", "detail", "detailed", "track", "record"}
_MONTH_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
                "nov": 11, "dec": 12, "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12}
_NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
     "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"])}
_SCALES = {"million": "million", "billion": "billion", "thousand": "thousand", "k": "thousand", "m": "million",
           "percent": "%", "%": "%"}
_AMOUNT = re.compile(r"(?<![A-Za-z0-9])\$?(\d[\d,]*(?:\.\d+)?)\s*(million|billion|thousand|percent|%|k\b|m\b)?", re.I)
_MM_YY = re.compile(r"\b(\d{1,2})/(\d{2})\b")
_MON_YYYY = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{4})\b")
_YYYY = re.compile(r"\b(19\d{2}|20\d{2})\b")
_CAP_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&.\-]*")


def _content_stems(text: str) -> set[str]:
    return {_stem(w) for w in _TOKEN.findall(text or "") if w.lower() not in _STOP and len(w) > 2}


def _covered(stems: set[str], evidence: set[str]) -> set[str]:
    """Stems the evidence supports: equal, or sharing a prefix of at least 5 letters up to 7 (coordination ~ coordinator)."""
    out = set()
    for s in stems:
        for e in evidence:
            if s == e:
                out.add(s)
                break
            n = min(len(s), len(e), 7)
            if n >= 5 and s[:n] == e[:n]:
                out.add(s)
                break
    return out


def _amounts(text: str) -> set[tuple[str, str]]:
    """(number, scale) pairs: '$10 million' -> ('10', 'million'); 'six' -> ('6', ''); '40%' -> ('40', '%')."""
    out = set()
    for m in _AMOUNT.finditer(text or ""):
        out.add((_number_key(m.group(1)), _SCALES.get((m.group(2) or "").lower(), "")))
    for w in _TOKEN.findall(text or ""):
        if w.lower() in _NUMBER_WORDS:
            out.add((_NUMBER_WORDS[w.lower()], ""))
    return out


def _fmt(amount: tuple[str, str]) -> str:
    num, scale = amount
    return f"{num} {scale}".strip()


def _proper_names(sentence: str) -> list[str]:
    """Capitalised or acronym words that are not the first word of the sentence (a named tool, employer or product)."""
    names = []
    for i, m in enumerate(_CAP_WORD.finditer(sentence or "")):
        w = m.group(0).strip(".-&")
        if i == 0 or len(w) < 2 or w.lower() in _STOP or w.lower() in _MONTH_NAMES or w.lower() == "i":
            continue
        if w[:1].isupper():
            names.append(w)
    return names


def _years_in(text: str) -> set[int]:
    years = {int(y) for y in _YYYY.findall(text or "")}
    for _month, yy in _MM_YY.findall(text or ""):
        years.add(2000 + int(yy))
    return years


def _parse_point(part: str):
    part = part.strip()
    if re.search(r"\b(present|current|now)\b", part, re.I):
        return "present"
    m = _MM_YY.search(part)
    if m and 1 <= int(m.group(1)) <= 12:
        return (2000 + int(m.group(2)), int(m.group(1)))
    m = _MON_YYYY.search(part)
    if m and m.group(1).lower() in _MONTH_NAMES:
        return (int(m.group(2)), _MONTH_NAMES[m.group(1).lower()])
    m = _YYYY.search(part)
    if m:
        return (int(m.group(1)), None)
    return None


def _parse_range(entry: str, organization: str = ""):
    """(start, end) parsed from an experience subtitle, or None if no dates. The employer name is removed first."""
    body = entry or ""
    if organization:
        body = re.sub(re.escape(organization), " ", body, flags=re.I)
    points = [p for p in (_parse_point(x) for x in re.split(r"\s*(?:–|—|-|\bto\b)\s*", body) if x.strip()) if p is not None]
    if not points:
        return None
    return (points[0] if points[0] != "present" else None), (points[1] if len(points) > 1 else None)


def _source_range(role: dict):
    """Saved (start, end). Month is used only where saved; years alone give year-level dates."""
    if role.get("start") is not None or role.get("end") is not None:
        return role.get("start"), role.get("end")
    years = sorted({int(y) for y in role.get("years") or []})
    if not years:
        return None, None
    if len(years) == 1:
        return (years[0], None), None
    return (years[0], None), (years[-1], None)


def _compare_point(gen, src, label: str):
    """Classify one generated date against one saved date. Never assumes a month the saved data does not contain."""
    if src is None:
        return UNCERTAIN, f"{label}: no saved {label} date to compare; confirm with the member."
    if gen == "present":
        return (UNSUPPORTED, f"{label}: states an ongoing role; saved data has an end date.") if src != "present" else (SUPPORTED, f"{label} matches.")
    gy, gm = gen
    sy, sm = src
    if gy != sy:
        return UNSUPPORTED, f"{label} year {gy} differs from the saved {sy}."
    if gm is None:
        return SUPPORTED, f"{label} year matches the saved data."
    if sm is None:
        return UNCERTAIN, f"{label} month is not in the saved data (only the year is saved). No month is assumed; confirm with the member."
    if gm != sm:
        return UNSUPPORTED, f"{label} month differs from the saved data."
    return SUPPORTED, f"{label} month and year match the saved data."


def _role_ref(role: dict) -> str:
    return f"role {role.get('id', '?')} ({role.get('title', '')}, {role.get('organization', '')})"


def _match_role(job: dict, roles: list[dict]):
    """Match a generated experience entry to one saved role by title AND employer, then by dates if the same title and employer repeat.
    Returns (role, None) or (None, reason) with reason in {title, employer, ambiguous}."""
    title = (job.get("title") or "").strip()
    subtitle = job.get("subtitle") or ""
    same_title = [r for r in roles if (r.get("title") or "").strip() == title]
    if not same_title:
        return None, "title"
    same_org = [r for r in same_title if (r.get("organization") or "").strip() and r["organization"].lower() in subtitle.lower()]
    if not same_org:
        return None, "employer"
    if len(same_org) == 1:
        return same_org[0], None
    parsed = _parse_range(subtitle, "")
    if parsed and parsed[0]:
        by_year = [r for r in same_org if _source_range(r)[0] and _source_range(r)[0][0] == parsed[0][0]]
        if len(by_year) == 1:
            return by_year[0], None
    return None, "ambiguous"


def _check_roles(resume: dict, facts: dict) -> list[dict]:
    """Title, employer and dates of each generated experience entry against its matched saved role (exact where saved)."""
    findings = []
    roles = facts.get("roles") or []
    for j_i, job in enumerate(resume.get("experience") or []):
        where = f"experience[{j_i}]"
        title = (job.get("title") or "").strip()
        subtitle = job.get("subtitle") or ""
        role, reason = _match_role(job, roles)
        if role is None:
            text = {"title": "Job title does not match any saved role; titles must be exact.",
                    "employer": "No saved role with this title is at the employer named in the entry.",
                    "ambiguous": "Matches more than one saved role (same title and employer); the member must choose the correct one."}[reason]
            cls = UNCERTAIN if reason == "ambiguous" else UNSUPPORTED
            findings.append(_finding(where, title, cls, None, text))
            continue
        ref = _role_ref(role)
        worst, notes = SUPPORTED, []
        src_start, src_end = _source_range(role)
        parsed = _parse_range(subtitle, role.get("organization", ""))
        if parsed is None or (parsed[0] is None and parsed[1] is None):
            # Absent or unreadable dates can never be verified: the member must confirm them (no month is ever invented).
            worst = UNCERTAIN
            notes.append("The entry has no readable employment dates, so they cannot be verified. The member must confirm them.")
        else:
            gen_start, gen_end = parsed
            if gen_start is not None:
                cls, msg = _compare_point(gen_start, src_start, "start")
                notes.append(msg)
                worst = max(worst, cls, key=_RANK.get)
            elif src_start is not None:
                worst = max(worst, UNCERTAIN, key=_RANK.get)
                notes.append("Start date is missing from the entry; the member must confirm it.")
            if gen_end is not None:
                cls, msg = _compare_point(gen_end, src_end, "end")
                notes.append(msg)
                worst = max(worst, cls, key=_RANK.get)
            elif src_end is not None:
                worst = max(worst, UNCERTAIN, key=_RANK.get)
                notes.append("End date is missing from the entry; the member must confirm it.")
        if worst == SUPPORTED:
            notes.insert(0, "Title and employer match the saved role.")
        findings.append(_finding(where, subtitle or title, worst, ref, " ".join(notes)))
    return findings


def _ordered_stems(text: str) -> list[str]:
    """Content stems in their original order, with number words written as digits ('six' and '6' compare equal)."""
    out = []
    for w in _TOKEN.findall(text or ""):
        low = w.lower()
        if low in _NUMBER_WORDS:
            out.append(_NUMBER_WORDS[low])
        elif low not in _STOP and len(low) > 2:
            out.append(_stem(low))
    return out


def _norm_text(text: str) -> str:
    return " ".join(_TOKEN.findall((text or "").lower()))


# Words whose deletion can reverse or materially change a claim: negation, and qualifiers of responsibility, assistance, limits and scope.
_NEGATION_TOKENS = {"not", "no", "never", "without", "nor", "none", "neither", "cannot", "unable", "didn", "don", "doesn", "isn",
                    "wasn", "weren", "won", "couldn", "wouldn", "shouldn", "t"}
_QUALIFIER_TOKENS = {"assist", "assisted", "assisting", "assistance", "help", "helped", "helping", "support", "supported",
                     "supporting", "contribute", "contributed", "contributing", "only", "limited", "limit", "partial", "partially",
                     "partly", "part", "some", "minor", "occasional", "occasionally", "shared", "alongside", "supervised",
                     "supervision", "under", "deputy", "backup", "behalf"}


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _TOKEN.findall(text or "")}


def _deletion_changes_meaning(bullet: str, source: str) -> bool:
    """True if the bullet drops a negation or a meaning-changing qualifier that the saved sentence contains."""
    return bool(((_tokens(source) & (_NEGATION_TOKENS | _QUALIFIER_TOKENS)) - _tokens(bullet)))


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(any(h == n for h in it) for n in needle)


def _evidence_preserving_sentence(bullet: str, sentences: list[str]):
    """The saved sentence this bullet reproduces exactly, or by deleting words only (same words, same order, nothing added).
    Anything else, including reordered or substituted words, is not evidence-preserving and returns None."""
    norm = _norm_text(bullet)
    for s in sentences:
        if _norm_text(s) == norm:
            return s
    b = _ordered_stems(bullet)
    if not b:
        return None
    for s in sentences:
        src = _ordered_stems(s)
        if set(b) <= set(src) and _is_subsequence(b, src) and not _deletion_changes_meaning(bullet, s):
            return s
    return None


def _narrow_source(bullet: str, kept: str) -> str:
    """The single saved line within `kept` that the bullet matches under the same rule. Falls back to `kept` when no single line does."""
    for unit in _statement_units(kept):
        if unit != kept and _evidence_preserving_sentence(bullet, [unit]) is not None:
            return unit
    return kept


def _check_bullets(resume: dict, facts: dict) -> list[dict]:
    """Bullet-level checks for entries matched to a saved role. SUPPORTED only for an exact or evidence-preserving match
    (words kept, in saved order, nothing added). Word overlap alone is never enough: rearranged or substituted wording is
    UNCERTAIN for member review. Invented amounts, scope and credentials are UNSUPPORTED. Unrecognised names are UNCERTAIN."""
    findings = []
    roles = facts.get("roles") or []
    for j_i, job in enumerate(resume.get("experience") or []):
        role, _ = _match_role(job, roles)
        if role is None:
            continue  # the entry is already reported by _check_roles
        src_text = " ".join([role.get("title", ""), role.get("organization", ""), role.get("text", "")])
        src_stems = _content_stems(src_text)
        src_amounts = _amounts(src_text)
        src_low = src_text.lower()
        sentences = _sentences(role.get("text", ""))
        for k, bullet in enumerate(job.get("bullets") or []):
            where = f"experience[{j_i}].bullets[{k}]"
            text = str(bullet)
            tokens = {w.lower() for w in _TOKEN.findall(text)}
            issues = []
            for amount in sorted(_amounts(text) - src_amounts):
                issues.append((UNSUPPORTED, f"States the amount '{_fmt(amount)}', which the saved data does not contain."))
            for scope in BULLET_SCOPE_WORDS:
                if scope in tokens and _stem(scope) not in src_stems:
                    issues.append((UNSUPPORTED, f"Claims scope ('{scope}') that the saved data does not describe."))
            for word in CREDENTIAL_UPGRADES:
                if word in tokens and word not in src_low:
                    issues.append((UNSUPPORTED, f"States a '{word}' credential that the saved data does not contain."))
            added_negation = (tokens & _NEGATION_TOKENS) - _tokens(src_text)
            if added_negation:
                issues.append((UNCERTAIN, "Adds a negation (" + ", ".join(sorted(added_negation)) + ") that the saved data does not contain. Confirm the meaning."))
            for name in _proper_names(text):
                if not _covered({_stem(name.lower())}, src_stems):
                    issues.append((UNCERTAIN, f"Names '{name}', which is not in the saved data. Confirm it with the member or remove it."))
            stems = _content_stems(text)
            if stems:
                covered = _covered(stems, src_stems)
                if not covered:
                    issues.append((UNSUPPORTED, "None of this bullet's content is in the saved data for this role."))
                elif covered != stems:
                    missing = ", ".join(sorted(stems - covered))
                    issues.append((UNCERTAIN, f"Only part is in the saved data (not found: {missing}). Confirm with the member."))
            if not issues:
                kept = _evidence_preserving_sentence(text, sentences)
                if kept is not None:
                    # Display only: name the saved line the bullet came from, not the whole role block. The classification above is unchanged.
                    shown = _narrow_source(text, kept)
                    findings.append(_finding(where, text, SUPPORTED, f"{_role_ref(role)}: \"{shown}\"",
                                             "Exact or evidence-preserving match: the saved words, in saved order, with nothing added."))
                else:
                    issues.append((UNCERTAIN, "Built from saved words but rearranged or reworded, so the meaning may differ. "
                                              "Confirm with the member before this is treated as established."))
            for cls, msg in issues:
                findings.append(_finding(where, text, cls, _role_ref(role), msg))
    return findings


def _finding(where, text, classification, source, explanation):
    return {"where": where, "text": text, "classification": classification, "source": source, "explanation": explanation}


def _source_refs(facts: dict) -> list[tuple[str, str]]:
    refs = []
    for role in facts.get("roles") or []:
        refs.append((_role_ref(role), role.get("text", "")))
    for i, edu in enumerate(facts.get("education") or []):
        refs.append((f"education {i + 1} ({edu.get('school', '')})", edu.get("text", "")))
    for cert in facts.get("certifications") or []:
        refs.append((f'certification "{cert.get("name", "")}"', " ".join(x for x in (cert.get("name", ""), cert.get("issuer", "")) if x)))
    return refs


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _statement_units(text: str) -> list[str]:
    """The sentences of a saved text, and each of its lines: a saved bullet line is a statement of its own. An exact repeat of one of
    these units is the same wording in the same saved context (its role, education or certification), so it can be SUPPORTED."""
    units = []
    for line in str(text or "").splitlines():
        units.extend(_sentences(line))
    return units


def _all_source_stems(facts: dict) -> set[str]:
    stems: set[str] = set()
    for _, text in _source_refs(facts):
        stems |= _content_stems(text)
    for skill in facts.get("skills") or []:
        stems |= _content_stems(skill)
    for role in facts.get("roles") or []:
        stems |= _content_stems(role.get("title", "")) | _content_stems(role.get("organization", ""))
    for edu in facts.get("education") or []:
        stems |= _content_stems(edu.get("school", "")) | _content_stems(edu.get("degree", ""))
    return stems


def _all_source_amounts(facts: dict) -> set[tuple[str, str]]:
    amounts: set[tuple[str, str]] = set()
    for _, text in _source_refs(facts):
        amounts |= _amounts(text)
    return amounts


def _check_skills(resume: dict, facts: dict) -> list[dict]:
    findings = []
    saved = [_content_stems(s) for s in facts.get("skills") or []]
    roles = facts.get("roles") or []
    sentences = [(ref, s) for ref, text in _source_refs(facts) for s in _sentences(text)]
    # A rule marked "unit": "statement" reads each saved line as its own statement, so a saved bullet without a final stop never runs
    # into the next line. Other rules keep their existing sentence reading.
    statements_ = [(ref, s) for ref, text in _source_refs(facts) for s in _statement_units(text)]
    for i, skill in enumerate(resume.get("skills") or []):
        where, label = f"skills[{i}]", str(skill).strip()
        stems = _content_stems(label)
        if stems and any(stems == s for s in saved if s):
            findings.append(_finding(where, label, SUPPORTED, "saved skill", "Matches a skill the member saved."))
            continue
        derived = None
        for role in roles:
            tw = (role.get("title") or "").split()
            if len(tw) >= 2 and tw[-1].lower() in TITLE_FORMS and label.lower() == " ".join(tw[:-1]).lower() + " " + TITLE_FORMS[tw[-1].lower()]:
                derived = (_role_ref(role) + " title", "Named from a held role title (the same activity, as a skill).")
                break
        if derived is None:
            for rule in DERIVATION_RULES:
                if label.lower() != rule["label"].lower():
                    continue
                for ref, sentence in (statements_ if rule.get("unit") == "statement" else sentences):
                    toks = _token_set(sentence)
                    if _rule_rejects(sentence, rule):
                        continue
                    if _has_prefix(toks, rule["verbs"]) and _has_prefix(toks, rule["objects"]):
                        derived = (f"{ref}: \"{sentence}\"", f"Derived by rule '{rule['label']}': a verb and a process object in one source sentence.")
                        break
                if derived is None and "reject" not in rule and any(_has_prefix(_token_set(s), rule["verbs"]) for _, s in sentences):
                    findings.append(_finding(where, label, UNCERTAIN, None,
                                             "The source describes an improvement but names no clear process. Confirm with the member before listing."))
                    derived = ("uncertain", "")
        if derived is None:
            findings.append(_finding(where, label, UNSUPPORTED, None,
                                     "No saved skill, held title or source sentence supports this skill. Do not list it as a qualification."))
        elif derived[0] != "uncertain":
            findings.append(_finding(where, label, DERIVED, derived[0], derived[1]))
    return findings


def _rule_rejects(sentence: str, rule: dict) -> bool:
    """True when a derivation rule's own context words (negation, hypothesis, plan) make the statement unfit as evidence."""
    words = set(re.findall(r"[a-z]+", sentence.lower()))
    return any(w in words for w in rule.get("reject", ()))


def _has_prefix(token_stems: set[str], prefixes) -> bool:
    return any(t.startswith(p) for t in token_stems for p in prefixes)


def _check_headline(resume: dict, facts: dict) -> list[dict]:
    headline = (resume.get("headline") or "").strip()
    if not headline:
        return []
    held = {(r.get("title") or "").lower(): (r.get("title") or "") for r in facts.get("roles") or []}
    evidence = _all_source_stems(facts)
    findings = []
    for seg_i, seg in enumerate(p.strip() for p in headline.split("|") if p.strip()):
        where = f"headline[{seg_i}]"
        words = seg.split()
        titled = len(words) >= 2 and all(w[:1].isupper() for w in words if w[:1].isalpha())
        if titled and words[-1].lower() in ROLE_NOUNS:
            if seg.lower() in held:
                findings.append(_finding(where, seg, SUPPORTED, f"held title \"{held[seg.lower()]}\"", "Matches a held role title."))
            else:
                findings.append(_finding(where, seg, UNSUPPORTED, None,
                                         "Presented as a held job title, but the saved roles contain no such title. Use a held title or a descriptive phrase."))
            continue
        stems = _content_stems(seg)
        if not stems:
            continue
        covered = _covered(stems, evidence)
        exact_skill = next((sk for sk in (facts.get("skills") or []) if _norm_text(sk) == _norm_text(seg)), None)
        if seg.lower() in held:
            findings.append(_finding(where, seg, SUPPORTED, f"held title \"{held[seg.lower()]}\"", "Matches a held role title exactly."))
        elif exact_skill is not None:
            # A saved skill does not make the same words true as a headline, which states a professional title or claim (F3).
            findings.append(_finding(where, seg, UNCERTAIN, None, HEADLINE_SKILL_EXPLANATION))
        elif not covered:
            findings.append(_finding(where, seg, UNSUPPORTED, None, "None of this headline's content words are in the member's saved data."))
        elif covered == stems:
            # Word overlap alone is never support: the wording is plausible but not an exact saved item, so the member confirms it.
            findings.append(_finding(where, seg, UNCERTAIN, None,
                                     "Built from words in your saved data, but not an exact match to it. Confirm it is true for you."))
        else:
            missing = ", ".join(sorted(stems - covered))
            findings.append(_finding(where, seg, UNCERTAIN, None, f"Only part is in the member's saved data (not found: {missing}). Confirm with the member."))
    return findings


HEADLINE_SKILL_EXPLANATION = ("This matches a skill you saved, but a headline states a professional title or claim, not a skill. "
                              "Confirm it is true for you before it is used.")

_CONNECTORS = {"holds", "has", "a", "an", "the", "earned", "obtained", "completed", "in"}


def _exact_saved_statement(sentence: str, saved_sentences: list, saved_facts: list):
    """The saved source for a sentence that exactly repeats saved information (a saved sentence, or a saved credential or title with
    only connector words such as 'Holds a'), or None."""
    norm = _norm_text(sentence)
    for src in saved_sentences:
        if _norm_text(src) == norm:
            return f"saved text: \"{src}\""
    words = [w for w in norm.split() if w not in _CONNECTORS]
    for fact in saved_facts:
        fw = [w for w in _norm_text(fact).split() if w not in _CONNECTORS]
        if fw and words == fw:
            return f"saved credential or title: \"{fact}\""
    return None


def _check_summary(resume: dict, facts: dict) -> list[dict]:
    evidence = _all_source_stems(facts)
    saved_sentences = [s for _, text in _source_refs(facts) for s in _statement_units(text)]
    saved_facts = [c.get("name", "") for c in facts.get("certifications") or [] if c.get("name")]
    saved_facts += [e.get("degree", "") for e in facts.get("education") or [] if e.get("degree")] +                   [r.get("title", "") for r in facts.get("roles") or [] if r.get("title")]
    evidence_amounts = _all_source_amounts(facts)
    evidence_text = " ".join(t for _, t in _source_refs(facts)).lower() + " " + " ".join(str(s) for s in facts.get("skills") or []).lower()
    edu_text = " ".join((e.get("degree", "") + " " + e.get("text", "")) for e in facts.get("education") or []).lower()
    edu_text += " " + " ".join(str(c.get("name", "")) for c in facts.get("certifications") or []).lower()
    findings = []
    for s_i, sentence in enumerate(_sentences(resume.get("summary") or "")):
        where = f"summary[{s_i}]"
        low = sentence.lower()
        tokens = {w.lower() for w in _TOKEN.findall(sentence)}
        for amount in sorted(_amounts(sentence) - evidence_amounts):
            findings.append(_finding(where, sentence, UNSUPPORTED, None, f"States the amount '{_fmt(amount)}', which the saved data does not contain."))
        for word in CREDENTIAL_UPGRADES:
            if word in tokens and word not in edu_text:
                findings.append(_finding(where, sentence, UNSUPPORTED, None,
                                         f"States a '{word}' credential; the saved education is a certificate or degree. Use the credential type as saved."))
        for pattern in SOFT_CLAIM_PATTERNS:
            if re.search(pattern, low) and not re.search(pattern, evidence_text):
                findings.append(_finding(where, sentence, UNSUPPORTED, None,
                                         f"Personal or performance claim ('{pattern.replace('-', ' ')}') with no source in the member's data."))
        for scope in SCOPE_WORDS:
            if scope in tokens and _stem(scope) not in evidence:
                findings.append(_finding(where, sentence, UNSUPPORTED, None,
                                         f"Overstates the member's scope ('{scope}') beyond the saved data."))
        local = []
        stems = _content_stems(sentence)
        if stems:
            covered = _covered(stems, evidence)
            if not covered:
                local.append(_finding(where, sentence, UNSUPPORTED, None, "No content of this sentence is in the member's saved data."))
        if not any(f["classification"] == UNSUPPORTED for f in local) and not any(f["classification"] == UNSUPPORTED for f in findings if f["where"] == where):
            exact = _exact_saved_statement(sentence, saved_sentences, saved_facts)
            if exact is not None:
                local = [_finding(where, sentence, SUPPORTED, exact, "Matches your saved information exactly.")]
            else:
                local = [f for f in local if f["classification"] == UNSUPPORTED] or [_finding(where, sentence, UNCERTAIN, None,
                         "Not an exact match to your saved information. Confirm the statement is true for you before it is used.")]
        findings.extend(local)
    return findings


def _check_education(resume: dict, facts: dict) -> list[dict]:
    findings = []
    edus = facts.get("education") or []
    for e_i, line in enumerate(resume.get("education") or []):
        where, text = f"education[{e_i}]", str(line)
        saved = next((e for e in edus if e.get("school") and e["school"].lower() in text.lower()), None)
        if saved is None:
            findings.append(_finding(where, text, UNSUPPORTED, None, "School does not match a saved education entry."))
            continue
        saved_text = (saved.get("degree", "") + " " + saved.get("text", "")).lower()
        bad = next((w for w in CREDENTIAL_TYPES if w in text.lower() and w not in saved_text), None)
        if bad:
            findings.append(_finding(where, text, UNSUPPORTED, f"education \"{saved['school']}\"", f"Credential type '{bad}' is not the saved credential type."))
        else:
            findings.append(_finding(where, text, SUPPORTED, f"education \"{saved['school']}\"", "School and credential type match saved data."))
    return findings


def _cert_tokens(text: str) -> list[str]:
    """Words of a certification line in order, lower-cased, with dates removed. Punctuation and spacing are not words."""
    return [w.lower() for w in _TOKEN.findall(_MM_YY.sub(" ", _YYYY.sub(" ", text or "")))]


def _contains_run(tokens: list[str], run: list[str]) -> int:
    """Index of the first occurrence of run inside tokens, or -1."""
    n = len(run)
    for i in range(len(tokens) - n + 1):
        if tokens[i:i + n] == run:
            return i
    return -1


def _check_certifications(resume: dict, facts: dict) -> list[dict]:
    """A certification line is SUPPORTED only when it states the complete saved certification name (formatting differences such as
    case, punctuation and spacing are ignored), and its issuer and date, if stated, match the saved ones. Anything shorter, any
    other name, credential type, issuer or date is UNSUPPORTED. Nothing here is UNCERTAIN, so no member decision can confirm it."""
    saved = [c for c in facts.get("certifications") or [] if c.get("name")]
    findings = []
    for c_i, line in enumerate(resume.get("certifications") or []):
        where, text = f"certifications[{c_i}]", str(line).strip()
        if not text:
            continue
        tokens = _cert_tokens(text)
        # The saved certification whose complete name appears in the line (the longest such name, if several do).
        matches = [(len(_cert_tokens(c["name"])), c) for c in saved if _cert_tokens(c["name"])
                   and _contains_run(tokens, _cert_tokens(c["name"])) >= 0]
        if not matches:
            findings.append(_finding(where, text, UNSUPPORTED, None,
                                     "The complete name of this certification is not in your saved certifications. Remove it, or add it to your saved certifications."))
            continue
        _, c = max(matches, key=lambda m: m[0])
        source = f'certification "{c["name"]}"'
        name = _cert_tokens(c["name"])
        at = _contains_run(tokens, name)
        remainder = tokens[:at] + tokens[at + len(name):]
        issuer = _cert_tokens(c.get("issuer", ""))
        if remainder and remainder != issuer:
            findings.append(_finding(where, text, UNSUPPORTED, source,
                                     "Adds an issuer or other detail that does not match your saved certification."))
        elif _years_in(text) - _years_in(c.get("date", "")):
            findings.append(_finding(where, text, UNSUPPORTED, source,
                                     "States a date that does not match your saved certification."))
        else:
            findings.append(_finding(where, text, SUPPORTED, source, "Matches your saved certification."))
    return findings


def general_truth_findings(resume: dict, facts: dict) -> list[dict]:
    """Structured truthfulness findings for a general résumé against the member's saved data. Step A: a checker only; it is not wired
    into generation or download. Each finding: {where, text, classification, source, explanation}. Inputs are never modified."""
    resume = copy.deepcopy(resume or {})
    facts = copy.deepcopy(facts or {})
    return (_check_roles(resume, facts) + _check_bullets(resume, facts) + _check_education(resume, facts)
            + _check_headline(resume, facts) + _check_summary(resume, facts) + _check_skills(resume, facts)
            + _check_certifications(resume, facts))
