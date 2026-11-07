"""Where each statement on a finished resume came from (Priority 1, PR-2). No AI, no migration.

The evidence rule: a substantive claim may appear on the resume only if the candidate's own history states it, and a bullet only in the role where
it was stated. The writer can still weave in the posting's own vocabulary or borrow a phrase from another role; the checks before this one
cover figures, struck qualifications and verb strength, not those two. This module compares what was written with what the candidate saved:

  bullets   every bullet is compared with the saved entry of the SAME role (its title, employer, sentences and role skills). A harmless
            paraphrase (at most one new word, nothing from another role or the posting) is kept and listed as "kept, not verified". Anything else is
            a new factual assertion: words from another role, the posting's wording, or two or more new content words. It is put back to the
            candidate's own sentences for that role (all the ones it draws on), or held out when none covers it. A resume role that cannot be
            matched to a saved role is kept, named as unverified and not checked.
  summary   a sentence that places the candidate in the posting's role name ("well suited to a customer success environment") when their history
            does not say it, or that states a posting requirement the plan marks "none", is left out.
  skills    a skill that is a posting term the plan marks "none", is built from posting wording the history never states, or is a transferable term
            whose words are each in the history but never together ("Scheduling Calls"), and that the plan does not back, is removed.

Nothing is rewritten by a model: a line is kept, put back to the candidate's own words, or left out and reported. Words are compared by their
first five letters so a different ending is not a difference. Limits: it cannot see a new combination of words that each appear somewhere in the
history ("Scheduling Calls"); the term plan and its hedge checks cover that.
"""
import re

from career import resume_quality as rq

_ROLE_HEADER = re.compile(r"^-\s+(.+?)\s+at\s+(.+?)(?:\s+\(([^)]*)\))?\s*$")
_SECTION = re.compile(r"^[A-Z][A-Z &()/\-]+(?:\s*\([^)]*\))?:\s*$")
_PARTS = re.compile(r"\s*(?:&|/|,|\band\b)\s*", re.I)
_POSITIONING = re.compile(r"\b(?:well|ideally|perfectly|uniquely)\s+suited\b|\b(?:strong|great|good|ideal)\s+(?:fit|candidate|match)\b|\bready\s+to\s+(?:join|contribute|step)\b|\bpassionate\s+about\b", re.I)


def stems(text: str) -> set[str]:
    return {r[:5] for r in rq.distinct_roots(text)}


def parse_profile(profile_text: str) -> tuple[list[dict], str]:
    """(roles, everything else). A role is {title, organization, text, sentences}; `text` holds its title, employer and every line under it,
    `sentences` the candidate's own sentences for it. The rest (skills, education, certificates, languages) is general evidence, tied to no role."""
    roles: list[dict] = []
    general: list[str] = []
    current = None
    in_experience = False
    for raw in (profile_text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            current = None
            continue
        if _SECTION.match(line.strip()):
            in_experience = line.strip().upper().startswith("EXPERIENCE")
            current = None
            continue
        header = _ROLE_HEADER.match(line) if in_experience else None
        if header:
            current = {"title": header.group(1).strip(), "organization": header.group(2).strip(), "lines": []}
            roles.append(current)
        elif current is not None and line.startswith(" "):
            current["lines"].append(re.sub(r"^\s*[*\-•]\s*", "", line).strip())
        else:
            general.append(re.sub(r"^\s*[*\-•]\s*", "", line).strip())
    out = []
    for r in roles:
        body = "\n".join(r["lines"])
        out.append({"title": r["title"], "organization": r["organization"], "text": f"{r['title']} {r['organization']}\n{body}",
                    "sentences": [s for s in rq._evidence_sentences(body) if s]})
    return out, "\n".join(general)


def _same(a: str, b: str) -> bool:
    return bool(a) and rq.distinct_roots(a) == rq.distinct_roots(b) and bool(rq.distinct_roots(a))


def _match_role(job: dict, roles: list[dict]) -> dict | None:
    title = rq.distinct_roots(job.get("title", ""))
    subtitle = job.get("subtitle", "")
    for role in roles:
        if title == rq.distinct_roots(role["title"]) and rq.distinct_roots(role["organization"]) <= rq.distinct_roots(subtitle):
            return role
    return None


def _own_sentences_for(bullet: str, role: dict) -> list[str]:
    """Every saved sentence of this role that the bullet draws on: most of the sentence's own words are in the bullet (more than half, at
    least two; a very short sentence needs all of its words). A bullet that merges several of the candidate's sentences is put back to all of
    them, so nothing true is lost when it is restored."""
    wanted = stems(bullet)
    found = []
    for sentence in role["sentences"]:
        own = stems(sentence)
        shared = wanted & own
        if own and ((len(own) <= 2 and shared == own) or (len(shared) >= 2 and len(shared) * 2 > len(own))):
            found.append(sentence)
    return found


def _nearest_role(job: dict, roles: list[dict]) -> str:
    """The saved role that shares the most words with a resume role that could not be matched, for the notice ("did you mean ...")."""
    wanted = stems(f"{job.get('title', '')} {job.get('subtitle', '')}")
    best, best_score = "", 0
    for role in roles:
        score = len(wanted & stems(f"{role['title']} {role['organization']}"))
        if score > best_score:
            best, best_score = f"{role['title']} at {role['organization']}", score
    return best


def _words_for(text: str, wanted: set[str]) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", text) if stems(w) & wanted]


# ---- organising headings: the closed allowlist (v1, approved) and the four guards that decide whether a Skills group label part is only a heading
# A heading is a generic category word ("Tools", "Operations & Tools"); it asserts nothing, the skills under it carry the claims. A label that names a
# skill or domain ("Customer Service", "Customer Success") is a qualification and keeps the full evidence decision. Applies to Skills group labels ONLY
# (never headline phrases, summaries, skill items or bullets). The list is closed: an unknown word never qualifies, and nothing is added automatically.
HEADING_WORDS = frozenset({
    "tools", "operations", "team", "platforms", "systems", "technical", "technology", "applications", "software", "core", "key", "additional",
    "other", "general", "environments",
})
_TOKEN = re.compile(r"[a-z0-9]+")


def _token(word: str) -> str:
    """One lower-case word with a plural ending removed ('tools' and 'tool' are the same word). Whole words only: no stems, no prefixes."""
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    """Capitalisation and punctuation normalised ('Customer-Service' and 'customer service' agree), whole words in order."""
    return [_token(w) for w in _TOKEN.findall((text or "").lower())]


_HEADING_TOKENS = frozenset(_token(w) for w in HEADING_WORDS)


def _content(tokens: list[str]) -> list[str]:
    """The words that say something: filler words ('support', 'skills', 'and') are dropped, as everywhere else in this module."""
    return [t for t in tokens if rq.distinct_roots(t)]


def _has_phrase(haystack: list[str], needle: list[str]) -> bool:
    """True when `needle` appears in `haystack` as a run of complete words in order (no substring matches)."""
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def _vocabulary_ok(content: list[str]) -> bool:
    """Guard 1, closed vocabulary: at least one content word, and every content word is on the allowlist. An unknown word is never a heading."""
    return bool(content) and all(t in _HEADING_TOKENS for t in content)


def _not_a_plan_term(tokens: list[str], plan_terms: list[str]) -> bool:
    """Guard 2, plan: the label does not equal, contain or sit inside any plan term, at ANY support level (literal, related, transferable, none)."""
    for term in plan_terms:
        t = _tokens(term)
        if _has_phrase(t, tokens) or _has_phrase(tokens, t):
            return False
    return True


def _not_a_posting_phrase(tokens: list[str], posting_tokens: list[str]) -> bool:
    """Guard 3, posting, independent of the plan: a label of two or more words that the posting itself names as a phrase is a requirement. Every word
    counts here, filler included, so "Technical Support" is caught even though "support" is filler elsewhere."""
    return len(tokens) < 2 or not _has_phrase(posting_tokens, tokens)


def _not_the_role_name(content: list[str], title_tokens: list[str]) -> bool:
    """Guard 4, job title: a label made only of the posting's job-title words ("Operations" for an Operations Associate role) is a role claim."""
    return not title_tokens or not set(content) <= set(_content(title_tokens))


def _is_heading(part: str, plan_terms: list[str], posting_text: str, posting_title: str) -> bool:
    tokens = _tokens(part)
    content = _content(tokens)
    return (_vocabulary_ok(content) and _not_a_plan_term(tokens, plan_terms)
            and _not_a_posting_phrase(tokens, _tokens(posting_text)) and _not_the_role_name(content, _tokens(posting_title)))


def audit_and_repair(resume: dict, profile_text: str, posting_text: str, facts_text: str = "", posting_title: str = "", terms: list[dict] | None = None) -> tuple[dict, dict]:
    """Returns (checked resume, report). report = {restored, held, skills_removed, skills_detail, notes, unverified_roles} with plain-language
    reasons; every list is empty when nothing needed to change. The input is not modified."""
    from career.term_pipeline import term_in_text  # imported here: term_pipeline imports this module

    roles, general = parse_profile(profile_text)
    backed_terms = [t["term"] for t in terms or [] if t.get("support") in ("literal", "related")]
    none_terms = [t["term"] for t in terms or [] if t.get("support") == "none"]
    transferable_terms = [t["term"] for t in terms or [] if t.get("support") == "transferable"]
    facts = stems(facts_text)
    general_stems = stems(general) | facts
    whole = set(general_stems)
    for r in roles:
        whole |= stems(r["text"])
    # the places a set of words can appear together in the candidate's history: a saved sentence, a skill, a certificate, a school, a confirmed fact
    units = [stems(s) for r in roles for s in r["sentences"]] + [stems(x) for x in (general + "\n" + (facts_text or "")).splitlines() if x.strip()]
    posting = stems(posting_text)
    report = {"restored": [], "held": [], "skills_removed": [], "skills_detail": [], "labels": [], "notes": [], "unverified_roles": []}
    out = {**resume, "experience": [{**j, "bullets": list(j.get("bullets") or [])} for j in resume.get("experience") or []]}

    # ---- bullets: the same role only
    for job in out["experience"]:
        role = _match_role(job, roles)
        if role is None:
            # Kept (nothing true is deleted) but named: its lines could not be compared with anything the candidate saved.
            report["unverified_roles"].append({"title": job.get("title", ""), "subtitle": job.get("subtitle", ""), "nearest": _nearest_role(job, roles)})
            continue
        own = stems(role["text"]) | facts
        others: set[str] = set()
        names: dict[str, str] = {}
        for other in roles:
            if other is role:
                continue
            for st in stems(other["text"]) - general_stems:  # a skill, certificate or school is the candidate's own, not another role's
                others.add(st)
                names.setdefault(st, other["title"])
        where = f"bullet under \"{job.get('title', '')}\""
        kept: list[str] = []
        for bullet in job["bullets"]:
            new = stems(bullet) - own
            borrowed = new & others
            posting_only = (new & posting) - borrowed
            detail = new - general_stems
            # Harmless paraphrase: no more than one new word (a different verb) and nothing from another role or the posting. Anything else is
            # a new factual assertion and is never kept as written.
            if not borrowed and not posting_only and len(detail) < 2:
                if detail:
                    report["notes"].append({"where": where, "text": bullet, "words": _words_for(bullet, detail)})
                kept.append(bullet)
                continue
            if borrowed:
                reason = "uses wording from your " + " and ".join(sorted({names[st] for st in borrowed})) + " role"
            elif posting_only:
                reason = "uses the posting's wording, which your " + role["title"] + " entry does not say"
            else:
                reason = "adds new facts your " + role["title"] + " entry does not state"
            matches = _own_sentences_for(bullet, role)
            fresh = [m for m in matches if rq.distinct_roots(m) not in [rq.distinct_roots(b) for b in kept]]
            if fresh:
                kept.extend(fresh)
                report["restored"].append({"where": where, "before": bullet, "after": "; ".join(fresh), "basis": "put back to your own words for this role; the draft " + reason})
            elif matches:
                report["restored"].append({"where": where, "before": bullet, "after": "", "basis": "already stated in another line of this role; this one " + reason})
            else:
                report["held"].append({"where": where, "text": bullet, "problem": reason})
        job["bullets"] = kept

    # ---- summary: positioning under the posting's role name, or an unverified requirement stated as fact
    title_core = rq.distinct_roots(posting_title)
    sentences = [s for s in rq._SENTENCE_SPLIT.split(str(out.get("summary", "")).strip()) if s.strip()]
    keep_sentences = []
    for sentence in sentences:
        places_in_role = bool(_POSITIONING.search(sentence)) and len(title_core) >= 2 and len(title_core & rq.distinct_roots(sentence)) >= 2
        states = next((t for t in none_terms if term_in_text(t, sentence)), "")
        if places_in_role or states:
            report["held"].append({"where": "summary", "text": sentence.strip(),
                                   "problem": "places you in the posting's role name" if places_in_role else f"states \"{states}\", which your history does not establish"})
        else:
            keep_sentences.append(sentence.strip())
    if len(keep_sentences) != len(sentences):
        out["summary"] = " ".join(keep_sentences)

    # ---- the ONE evidence decision for a short label (a skill, a headline phrase, a skills group label). Never a requirement the history does not
    #      establish, posting wording it never states, or a transferable term whose words never appear together in it ("Scheduling Calls" from
    #      scheduling staff and a call-centre job). A label the plan backs (it IS a literal or related term) stays. Returns the reason, or "".
    def unsupported(text: str) -> str:
        def is_term(t: str) -> bool:
            return term_in_text(t, text) or rq.distinct_roots(t) == rq.distinct_roots(text)

        # backed means the label IS a backed term; one that merely contains a backed term and adds a word ('Scheduling Calls') is checked on its own
        if any(rq.distinct_roots(t) == rq.distinct_roots(text) for t in backed_terms):
            return ""
        if any(is_term(t) for t in none_terms):
            return "a requirement your history does not establish"
        if (stems(text) - whole) & posting:
            return "uses the posting's wording, which your history does not say"
        words = stems(next((t for t in transferable_terms if is_term(t)), ""))
        # a recombination only: every word is somewhere in the history, but never together. A label with a word the history never uses
        # ("Customer Service" for "assisted customers") is not a recombination, so this rule leaves it alone; the posting-wording rule above
        # has already removed it when the posting names the label and no confirmed fact supports it.
        if len(words) >= 2 and words <= whole and not any(words <= u for u in units):
            return "a transferable skill: its words never appear together in your history, so it is shown as relevant experience, not as a skill"
        return ""

    def screen(text: str, where: str) -> str:
        """A headline phrase or a group label may join several ideas ("De-Escalation & Complaint Resolution"). Each part gets the decision; only the
        unsupported parts go, the rest is kept. Returns the text to print ("" when nothing is left)."""
        parts = [x.strip() for x in _PARTS.split(text) if x.strip()]
        kept, dropped = [], []
        for part in parts:
            # a generic organising heading on a Skills group label is only a category; everything else gets the full evidence decision
            heading = where == "skills group label" and _is_heading(part, [t["term"] for t in terms or []], posting_text, posting_title)
            why = "" if heading else unsupported(part)
            (dropped if why else kept).append((part, why))
        for part, why in dropped:
            report["labels"].append({"where": where, "text": part, "why": why})
        return text if not dropped else " & ".join(p for p, _ in kept)

    # ---- headline: every phrase between the bars gets the decision
    headline = str(out.get("headline", "") or "")
    if headline.strip():
        phrases = [x.strip() for x in headline.split("|") if x.strip()]
        shown = [screen(x, "headline") for x in phrases]
        if shown != phrases:
            out["headline"] = " | ".join(x for x in shown if x)

    # ---- skills: each item, and each group label, gets the decision. Removing a label never removes the supported skills under it.
    new_lines = []
    changed = False
    for line in out.get("skills") or []:
        label, sep, rest = line.partition(":")
        grouped = bool(sep) and len(label) <= 40
        items = [i.strip() for i in (rest if grouped else line).split(",") if i.strip()]
        kept = []
        for item in items:
            why = unsupported(item)
            if why:
                report["skills_removed"].append(item)
                report["skills_detail"].append({"skill": item, "why": why})
                changed = True
            else:
                kept.append(item)
        shown_label = screen(label.strip(), "skills group label") if grouped else ""
        if grouped and shown_label != label.strip():
            changed = True
        if kept:
            new_lines.append(f"{shown_label}: {', '.join(kept)}" if grouped and shown_label else ", ".join(kept))
    if changed:
        out["skills"] = new_lines
    return out, report


def _removed_labels(report: dict) -> list[dict]:
    """Every label (a skill, a headline phrase, a group label) the check left out, ONCE per distinct label with every place it was left out."""
    found: dict[frozenset, dict] = {}
    detail = {d["skill"]: d["why"] for d in report.get("skills_detail") or []}
    rows = ([(l["text"], l["where"], l["why"]) for l in report.get("labels") or []]
            + [(s, "skills", detail.get(s, "not established by your own history")) for s in report.get("skills_removed") or []])
    for text, where, why in rows:
        key = frozenset(rq.distinct_roots(text)) or frozenset({text.lower()})
        entry = found.setdefault(key, {"text": text, "why": why, "where": []})
        if where not in entry["where"]:
            entry["where"].append(where)
    return list(found.values())


def notice_text(report: dict) -> dict:
    """The plain message and the list a candidate sees, or empty strings when nothing needs saying. Everything listed is a change, a line kept
    but not verified, or a role that could not be checked; none of it is ever presented as verified. A label left out in several places (the
    headline, a group label and the skills) is one item and one count."""
    restored, held = report.get("restored") or [], report.get("held") or []
    labels = _removed_labels(report)
    notes, roles = report.get("notes") or [], report.get("unverified_roles") or []
    changes = len(restored) + len(held) + len(labels)
    if not (changes or notes or roles):
        return {"count": 0, "message": "", "items": []}

    def places(where: list[str]) -> str:
        names = [{"headline": "headline", "skills group label": "skills group label", "skills": "skills"}.get(w, w) for w in where]
        return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]

    items = ([{"text": r["before"], "change": ("now reads: " + r["after"]) if r["after"] else "left out (already said elsewhere)", "why": r["basis"]} for r in restored]
             + [{"text": h["text"], "change": "left out", "why": h["problem"]} for h in held]
             + [{"text": l["text"], "change": "left out of your " + places(l["where"]), "why": l["why"]} for l in labels]
             + [{"text": r["title"] + (" \u2014 " + r["subtitle"] if r["subtitle"] else ""), "change": "kept, not checked",
                 "why": "we could not match this role to your saved profile" + (f" (did you mean {r['nearest']}?)" if r["nearest"] else "") + ", so its lines are not verified"} for r in roles]
             + [{"text": n["text"], "change": "kept, not verified", "why": "wording that is not word for word in your entry (" + ", ".join(n["words"]) + ")"} for n in notes])
    parts = ["We checked your r\u00e9sum\u00e9 against what you wrote in each role."]
    if changes:
        noun = "statement" if changes == 1 else "statements"
        parts.append(f"{changes} {noun} {'was' if changes == 1 else 'were'} not in your own words for that role, so we "
                     f"{'put it back to your wording or left it out' if changes == 1 else 'put them back to your wording or left them out'}.")
        parts.append("To include something that is true, add it to that role in your profile and rebuild.")
    if roles:
        parts.append(f"{len(roles)} {'role' if len(roles) == 1 else 'roles'} could not be matched to your saved profile, so {'its' if len(roles) == 1 else 'their'} lines were kept but not checked. "
                     "Add or correct it in your profile and rebuild.")
    if notes:
        parts.append(f"{len(notes)} {'line was' if len(notes) == 1 else 'lines were'} kept with a word that is not in your entry; {'it is' if len(notes) == 1 else 'they are'} not verified.")
    return {"count": len(items), "items": items, "message": " ".join(parts)}
