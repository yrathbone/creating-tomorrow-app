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
