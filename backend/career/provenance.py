"""Where each statement on a finished resume came from (Priority 1, PR-2). No AI, no migration.

The evidence rule: a substantive claim may appear on the resume only if the candidate's own history states it, and a bullet only in the role where
it was stated. The writer can still weave in the posting's own vocabulary or borrow a phrase from another role; the checks before this one
cover figures, struck qualifications and verb strength, not those two. This module compares what was written with what the candidate saved:

  bullets   every bullet is compared with the saved entry of the SAME role (its title, employer, sentences and role skills). Words the role never
            used that come from another role ("borrowed") or from the posting ("posting wording") make the bullet unverified. It is put back to
            the candidate's own sentence from that role, or held out of the resume when no sentence of theirs covers it. Other new words (a
            different verb, a descriptive phrase) are only reported as notes: a paraphrase is not a new claim, and a plain-word check cannot tell
            the two apart.
  summary   a sentence that places the candidate in the posting's role name ("well suited to a customer success environment") when their history
            does not say it, or that states a posting requirement the plan marks "none", is left out.
  skills    a skill that is a posting term the plan marks "none", or is built from posting wording the history never states and the plan does
            not back, is removed (so a transferable term the history does not state, such as "Customer Success", cannot be printed as a skill).

Nothing is rewritten by a model: a line is kept, put back to the candidate's own words, or left out and reported. Words are compared by their
first five letters so a different ending is not a difference. Limits: it cannot see a new combination of words that each appear somewhere in the
history ("Scheduling Calls"); the term plan and its hedge checks cover that.
"""
import re

from career import resume_quality as rq

_ROLE_HEADER = re.compile(r"^-\s+(.+?)\s+at\s+(.+?)(?:\s+\(([^)]*)\))?\s*$")
_SECTION = re.compile(r"^[A-Z][A-Z &()/\-]+(?:\s*\([^)]*\))?:\s*$")
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


def _own_sentence_for(bullet: str, role: dict) -> str:
    """The candidate's own saved sentence for this role that the bullet is built on: the most words in common, at least two."""
    wanted = stems(bullet)
    best, best_score = "", 1
    for sentence in role["sentences"]:
        score = len(wanted & stems(sentence))
        if score > best_score:
            best, best_score = sentence, score
    return best


def audit_and_repair(resume: dict, profile_text: str, posting_text: str, facts_text: str = "", posting_title: str = "", terms: list[dict] | None = None) -> tuple[dict, dict]:
    """Returns (checked resume, report). report = {restored: [...], held: [...], skills_removed: [...]} with plain-language reasons; every list
    is empty when nothing needed to change. The input is not modified."""
    from career.term_pipeline import term_in_text  # imported here: term_pipeline imports this module

    roles, general = parse_profile(profile_text)
    backed_terms = [t["term"] for t in terms or [] if t.get("support") in ("literal", "related")]
    none_terms = [t["term"] for t in terms or [] if t.get("support") == "none"]
    facts = stems(facts_text)
    general_stems = stems(general) | facts
    whole = set(general_stems)
    for r in roles:
        whole |= stems(r["text"])
    posting = stems(posting_text)
    report = {"restored": [], "held": [], "skills_removed": [], "notes": []}
    out = {**resume, "experience": [{**j, "bullets": list(j.get("bullets") or [])} for j in resume.get("experience") or []]}

    # ---- bullets: the same role only
    for job in out["experience"]:
        role = _match_role(job, roles)
        if role is None:
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
        kept = []
        for bullet in job["bullets"]:
            new = stems(bullet) - own
            borrowed = new & others
            posting_only = (new & posting) - borrowed
            if not borrowed and not posting_only:
                if new - general_stems:
                    report["notes"].append({"where": f"bullet under \"{job.get('title', '')}\"", "text": bullet, "added": sorted(new - general_stems)})
                kept.append(bullet)
                continue
            where = f"bullet under \"{job.get('title', '')}\""
            if borrowed:
                reason = "uses wording from your " + " and ".join(sorted({names[st] for st in borrowed})) + " role"
            else:
                reason = "uses the posting's wording, which your " + role["title"] + " entry does not say"
            own_sentence = _own_sentence_for(bullet, role)
            if own_sentence and not _same(own_sentence, bullet):
                if rq.distinct_roots(own_sentence) in [rq.distinct_roots(b) for b in kept]:
                    report["restored"].append({"where": where, "before": bullet, "after": "", "basis": "already stated in another line of this role; this one " + reason})
                else:
                    kept.append(own_sentence)
                    report["restored"].append({"where": where, "before": bullet, "after": own_sentence, "basis": "put back to your own sentence for this role; the draft " + reason})
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

    # ---- skills: never an unverified or only-transferable posting term, nor posting wording the history never states
    new_lines = []
    for line in out.get("skills") or []:
        label, sep, rest = line.partition(":")
        grouped = bool(sep) and len(label) <= 40
        items = [i.strip() for i in (rest if grouped else line).split(",") if i.strip()]
        kept = []
        for item in items:
            backed = any(term_in_text(t, item) or rq.distinct_roots(t) == rq.distinct_roots(item) for t in backed_terms)
            unverified = any(term_in_text(t, item) or rq.distinct_roots(t) == rq.distinct_roots(item) for t in none_terms)
            posting_wording = bool((stems(item) - whole) & posting)
            if (unverified or posting_wording) and not backed:
                report["skills_removed"].append(item)
            else:
                kept.append(item)
        if kept:
            new_lines.append(f"{label.strip()}: {', '.join(kept)}" if grouped else ", ".join(kept))
    if report["skills_removed"]:
        out["skills"] = new_lines
    return out, report


def notice_text(report: dict) -> dict:
    """The plain message and the list a candidate sees, or empty strings when nothing changed."""
    restored, held, skills = report.get("restored") or [], report.get("held") or [], report.get("skills_removed") or []
    total = len(restored) + len(held) + len(skills)
    if not total:
        return {"count": 0, "message": "", "items": []}
    items = ([{"text": r["before"], "change": ("now reads: " + r["after"]) if r["after"] else "left out (already said elsewhere)", "why": r["basis"]} for r in restored]
             + [{"text": h["text"], "change": "left out", "why": h["problem"]} for h in held]
             + [{"text": s, "change": "removed from your skills", "why": "not established by your own history"} for s in skills])
    noun = "statement" if total == 1 else "statements"
    return {"count": total, "items": items,
            "message": f"We checked your résumé against what you wrote in each role. {total} {noun} "
                       f"{'was' if total == 1 else 'were'} not in your own words for that role, so we {'put it back to your wording or left it out' if total == 1 else 'put them back to your wording or left them out'}. "
                       "To include something that is true, add it to that role in your profile and rebuild."}
