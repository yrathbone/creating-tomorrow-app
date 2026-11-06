"""Editable suggestions for a finished tailored resume (Priority 1, PR 6). No AI, no migration.

A posting term the candidate's evidence supports but that could not be placed on the resume ("not_placed") gets ONE suggestion: the
candidate's own saved sentence about it (a sentence that really is in one of their saved roles), offered as a new bullet under that role on
this resume. The candidate edits it, sees a before and after, and nothing changes until they add it. The change is saved to this resume
version only; their saved roles, global skills and decisions for other jobs are never touched, and every change can be undone.

Truth rules: the suggestion is built from the candidate's own sentence, never written by a model; an edited bullet may not contain a
figure that is not in the candidate's evidence; a role the resume left off is never revived; a sentence already on the resume is not offered.
"""
from career import resume_quality
from career.term_pipeline import normalize, resume_text, term_in_text, invented_figures

MAX_WORDS = 40
MAX_CHARS = 300
MAX_APPLIED = 10
MIN_SHARED_ROOTS = 2  # a related term needs at least this many content words in common between its evidence note and the sentence


def _role_index(resume_data: dict, experience: dict) -> int | None:
    """The position of a saved role on this resume: same job title, and the employer named in the subtitle."""
    for i, job in enumerate(resume_data.get("experience") or []):
        if normalize(job.get("title", "")) == normalize(experience.get("title", "")) and term_in_text(experience.get("organization", ""), job.get("subtitle", "")):
            return i
    return None


def _clean(sentence: str) -> str:
    text = " ".join(str(sentence or "").split()).strip(" -*•")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _best_sentence(item: dict, experience: dict, resume_blob: str) -> tuple[int, str]:
    """(score, sentence) of the saved sentence that best backs this term, or (0, "")."""
    term_roots = resume_quality.distinct_roots(item["term"])
    evidence_roots = resume_quality.distinct_roots(item.get("evidence", "")) - term_roots
    best = (0, "")
    for sentence in resume_quality._evidence_sentences(experience.get("description", "")):
        if term_in_text(item["term"], sentence):
            score = 100  # the term's own words are in the sentence
        else:
            shared = len(evidence_roots & resume_quality.distinct_roots(sentence))
            score = shared if item.get("support") == "related" and shared >= MIN_SHARED_ROOTS else 0
        if score > best[0] and len(sentence.split()) <= MAX_WORDS and normalize(sentence) not in resume_blob:
            best = (score, _clean(sentence))
    return best


def find_suggestions(resume_data: dict, term_report: list[dict], experiences: list[dict]) -> list[dict]:
    blob = normalize(resume_text(resume_data))
    found, used = [], set()
    for item in term_report or []:
        if item.get("status") != "not_placed" or item.get("kind") == "phrase":
            continue
        best = (0, "", None)
        for experience in experiences:
            index = _role_index(resume_data, experience)
            if index is None:
                continue  # the resume left this role off; it is not brought back here
            score, sentence = _best_sentence(item, experience, blob)
            if score > best[0]:
                best = (score, sentence, (index, experience))
        if best[0] and best[1] not in used:
            used.add(best[1])
            index, experience = best[2]
            job = resume_data["experience"][index]
            found.append({
                "term": item["term"], "importance": item.get("importance", "mentioned"), "support": item.get("support", ""),
                "experience_index": index, "role": job.get("title", ""), "organization": experience.get("organization", ""),
                "source_sentence": best[1], "suggested_text": best[1], "before_bullets": list(job.get("bullets") or []),
            })
    return found


def apply_suggestions(resume_data: dict, choices: list[dict], evidence_text: str) -> dict:
    """Adds the candidate's chosen (and possibly edited) bullets to this resume. Raises ValueError with a plain message when a choice is not
    allowed; nothing is changed in that case. Returns the new resume data (the input is not modified)."""
    if not choices:
        raise ValueError("Choose at least one suggestion to add.")
    resume = {**resume_data, "experience": [{**job, "bullets": list(job.get("bullets") or [])} for job in resume_data.get("experience") or []]}
    applied = list(resume_data.get("applied_suggestions") or [])
    if len(applied) + len(choices) > MAX_APPLIED:
        raise ValueError(f"No more than {MAX_APPLIED} suggestions can be added to one resume.")
    report = [dict(r) for r in resume_data.get("term_report") or []]
    for choice in choices:
        index, text = choice.get("experience_index"), " ".join(str(choice.get("text", "")).split())
        if not isinstance(index, int) or not 0 <= index < len(resume["experience"]):
            raise ValueError("That role is no longer on this resume.")
        if len(text.split()) < 3 or len(text.split()) > MAX_WORDS or len(text) > MAX_CHARS:
            raise ValueError(f"Keep each added bullet between 3 and {MAX_WORDS} words.")
        if invented_figures(text, evidence_text):
            raise ValueError("That bullet contains a number or amount that is not in your own experience. Remove it, or add it to your profile first.")
        bullets = resume["experience"][index]["bullets"]
        if normalize(text) in {normalize(b) for b in bullets}:
            raise ValueError("That bullet is already on this resume.")
        bullets.append(text)
        term = str(choice.get("term", ""))
        previous = next((r.get("status", "") for r in report if r.get("term") == term), "")
        applied.append({"term": term, "experience_index": index, "text": text, "previous_status": previous})
        blob = resume_text(resume)
        for r in report:
            if r.get("term") == term and term_in_text(term, blob):
                r["status"] = "on_resume"
    resume["applied_suggestions"] = applied
    resume["term_report"] = report
    return resume


def undo_suggestions(resume_data: dict) -> dict:
    """Removes every bullet added from suggestions and restores the term statuses, leaving the resume as it was built."""
    resume = {**resume_data, "experience": [{**job, "bullets": list(job.get("bullets") or [])} for job in resume_data.get("experience") or []]}
    report = [dict(r) for r in resume_data.get("term_report") or []]
    for entry in reversed(resume_data.get("applied_suggestions") or []):
        index = entry.get("experience_index")
        if isinstance(index, int) and 0 <= index < len(resume["experience"]) and entry.get("text") in resume["experience"][index]["bullets"]:
            resume["experience"][index]["bullets"].remove(entry["text"])
        for r in report:
            if r.get("term") == entry.get("term") and entry.get("previous_status"):
                r["status"] = entry["previous_status"]
    resume["applied_suggestions"] = []
    resume["term_report"] = report
    return resume
