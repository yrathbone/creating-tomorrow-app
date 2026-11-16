"""C-52 Step B: server-side review gate for general résumés.

Pure functions plus reads of saved career rows. The checker (career/resume_quality.py, accepted in Step A) decides what is
SUPPORTED, DERIVED, UNCERTAIN or UNSUPPORTED; this module stores the review, applies member decisions, finalises the content and
checks that approval and downloads use exactly what the member signed off.

Integrity rules:
- Hashes are over canonical JSON of the résumé content (review keys excluded, so a record cannot hash itself) and of the saved
  career facts the checker reads, plus the checker version.
- Every decision, sign-off, download and approval recomputes both hashes from the database and refuses on any mismatch (stale).
- Review data lives only in the server-side JSON of the version. A client cannot supply it: the build route ignores it.

Feature switch CT_GENERAL_RESUME_TRUTH_GATE: "off" (default: no review), "shadow" (review stored, nothing removed or gated),
"on" (unsupported statements removed before save; decisions, sign-off and approval gates enforced). Ownership and authentication
are never controlled by this switch; they live in the routes.
"""
import copy
import hashlib
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

from career.resume_quality import (HEADLINE_SKILL_EXPLANATION, _exact_saved_statement, _parse_point, _sentences, _source_refs,
                                   _statement_units, _years_in, general_truth_findings)

GATE_ENV = "CT_GENERAL_RESUME_TRUTH_GATE"
CHECKER_VERSION = "step-a-rev3"
# Keys that are never résumé content: the common member review and sign-off, the legacy general keys, and the job pipeline's own
# truth_review (kept out of the hashes exactly as before, so nothing already approved or signed changes).
REVIEW_KEYS = ("truth_review", "final_signoff", "member_review", "member_signoff", "member_review_history")
MEMBER_ONLY_KEYS = ("final_signoff", "member_review", "member_signoff", "member_review_history")
JOB_CHECKER = "job-pipeline-v1"
_PIPELINE_SUPPORTED = ("literal", "related")     # the job term plan's own support classes
_PIPELINE_TRANSFERABLE = "transferable"
_REMOVABLE = re.compile(r"^(skills\[\d+\]|experience\[\d+\]\.bullets\[\d+\]|headline\[\d+\]|summary\[\d+\]|certifications\[\d+\])$")
_MODES = ("off", "shadow", "on")


def gate_mode() -> str:
    value = os.environ.get(GATE_ENV, "off")
    return value if value in _MODES else "off"


def gate_on() -> bool:
    """True only when the switch is ON. SHADOW and OFF never block, sign off or gate anything for the member."""
    return gate_mode() == "on"


def _normalise(value):
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    return value


def _canon(value) -> str:
    return json.dumps(_normalise(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(resume: dict) -> str:
    """Hash of the résumé content, excluding the review keys so the review cannot hash itself."""
    base = {k: v for k, v in (resume or {}).items() if k not in REVIEW_KEYS}
    return hashlib.sha256(_canon(base).encode("utf-8")).hexdigest()


def facts_hash(facts: dict) -> str:
    # An empty certification list is left out, so profiles without certifications keep the hash they had before certifications
    # were evidence. Any saved certification (name, issuer or date) changes the hash, so earlier reviews and sign-offs go stale.
    payload = {k: v for k, v in (facts or {}).items() if not (k == "certifications" and not v)}
    return hashlib.sha256(_canon({"checker": CHECKER_VERSION, "facts": payload}).encode("utf-8")).hexdigest()


def build_facts(db, profile) -> dict:
    """The saved career facts the checker reads. Read-only."""
    from models import Certification, Education, Experience, Skill
    experiences = db.query(Experience).filter_by(career_profile_id=profile.id).order_by(Experience.id).all()
    skills = db.query(Skill).filter_by(career_profile_id=profile.id).order_by(Skill.id).all()
    education = db.query(Education).filter_by(career_profile_id=profile.id).order_by(Education.id).all()
    roles = []
    for e in experiences:
        tied = [s.name for s in skills if s.experience_id == e.id]
        text = " ".join(x for x in [(e.description or "").strip(), " ".join(tied)] if x)
        start_pt = _parse_point(e.start_date) if e.start_date else None
        end_pt = _parse_point(e.end_date) if e.end_date else None
        roles.append({
            "id": e.id, "title": e.title or "", "organization": e.organization or "",
            "years": sorted(_years_in(f"{e.start_date or ''} {e.end_date or ''}")),
            "start": start_pt if isinstance(start_pt, tuple) else None,
            "end": end_pt if isinstance(end_pt, tuple) else ("present" if end_pt == "present" else None),
            "text": text,
        })
    edus = [{"id": ed.id, "school": ed.institution or "",
             "degree": " ".join(x for x in [ed.degree or "", ed.field_of_study or ""] if x), "text": ""} for ed in education]
    certs = db.query(Certification).filter_by(career_profile_id=profile.id).order_by(Certification.id).all()
    certifications = [{"id": c.id, "name": c.name or "", "issuer": c.issuer or "", "date": c.date or ""} for c in certs]
    return {"roles": roles, "education": edus, "skills": [s.name for s in skills], "certifications": certifications}


def draft_of(data: dict) -> dict:
    """The résumé content plus the job pipeline's own record. Only the member's review state is removed: the job pipeline's truth_review
    (its claim, verb, held-line and provenance evidence) is kept, and a legacy general review is removed. Every member action stores
    the draft this returns, so no action can erase the job's record."""
    from career import member_review as mr
    return {k: v for k, v in (data or {}).items()
            if k not in MEMBER_ONLY_KEYS and not (k == "truth_review" and mr.is_general_shaped(v))}


def _classified(review: dict) -> dict:
    """Every statement the review classifies, keyed by (where, text). An uncertain statement is in items; a supported or derived one is in
    its own list. Every statement of the résumé is in exactly one of them."""
    out = {}
    for name in ("items", "supported", "derived"):
        for row in (review or {}).get(name) or []:
            out.setdefault((row.get("where") or "", row.get("text") or ""), row)
    return out


def review_changes(previous: dict, current: dict) -> list:
    """What a new check changed compared with the review it replaces. A statement's classification is compared across every list the
    review keeps, so a statement that moved from uncertain to supported is a change of classification, not a removal. A statement still
    in the résumé is never reported as removed or as no longer in the résumé. Each entry says what it was, what it is, and why."""
    before = _classified(previous)
    now = _classified(current)
    present = {text for _, text in now}
    changes = []
    for key, row in now.items():
        old = before.get(key)
        if old is not None and old.get("classification") == row.get("classification"):
            continue
        changes.append({"kind": "classification", "where": key[0], "text": key[1],
                        "before": old.get("classification") if old is not None else "not reviewed before",
                        "after": row.get("classification"), "why": row.get("explanation") or ""})
    for key, old in before.items():
        if key not in now and key[1] not in present:
            changes.append({"kind": "no longer in the review", "where": key[0], "text": key[1],
                            "before": old.get("classification"), "after": "not in the résumé",
                            "why": "The statement is no longer in the résumé."})
    old_removed = {(r.get("text") or "") for r in (previous or {}).get("removed", [])}
    for r in (current or {}).get("removed", []):
        text = r.get("text") or ""
        if text in old_removed or text in present:
            continue
        changes.append({"kind": "removed", "where": r.get("where") or "", "text": text, "before": "in the résumé",
                        "after": "removed", "why": r.get("explanation") or ""})
    return changes


def strip_review(data: dict) -> dict:
    return {k: x for k, x in (data or {}).items() if k not in REVIEW_KEYS}


def gate_token(draft: dict, review: dict, facts: dict) -> str:
    """One hash over everything a decision, preview or approval depends on: content, saved facts and claim decisions."""
    decisions = [[i["id"], i.get("decision"), bool(i.get("acknowledged"))] for i in (review or {}).get("items", [])]
    return hashlib.sha256(_canon({"content": content_hash(draft), "facts": facts_hash(facts), "decisions": decisions}).encode("utf-8")).hexdigest()


EDIT_MAX_LENGTH = 300


def replace_statement(draft: dict, where: str, old: str, new: str) -> dict:
    """A copy of the draft with the statement at `where` replaced. Raises ValueError when the statement there is no longer `old`
    (the review is stale) or when the location cannot be edited."""
    out = copy.deepcopy(draft or {})
    m = re.fullmatch(r"skills\[(\d+)\]", where)
    if m:
        i, skills = int(m.group(1)), out.get("skills")
        if not isinstance(skills, list) or i >= len(skills) or " ".join(str(skills[i]).split()) != old:
            raise ValueError("stale")
        skills[i] = new
        return out
    m = re.fullmatch(r"experience\[(\d+)\]\.bullets\[(\d+)\]", where)
    if m:
        j, k = int(m.group(1)), int(m.group(2))
        jobs = out.get("experience") or []
        if j >= len(jobs) or not isinstance(jobs[j].get("bullets"), list):
            raise ValueError("stale")
        bullets = jobs[j]["bullets"]
        if k >= len(bullets) or " ".join(str(bullets[k]).split()) != old:
            raise ValueError("stale")
        bullets[k] = new
        return out
    m = re.fullmatch(r"headline\[(\d+)\]", where)
    if m:
        i = int(m.group(1))
        segs = [p.strip() for p in str(out.get("headline") or "").split("|") if p.strip()]
        if i >= len(segs) or segs[i] != old:
            raise ValueError("stale")
        segs[i] = new
        out["headline"] = " | ".join(segs)
        return out
    m = re.fullmatch(r"summary\[(\d+)\]", where)
    if m:
        i = int(m.group(1))
        sents = _sentences(str(out.get("summary") or ""))
        if i >= len(sents) or " ".join(sents[i].split()) != old:
            raise ValueError("stale")
        sents[i] = new
        out["summary"] = " ".join(sents)
        return out
    raise ValueError("not editable")


def _norm_words(text) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def statements(resume: dict) -> list:
    """Every editable statement of a résumé, as (where, text), with the same locations the checker and the edit use."""
    out = []
    for i, skill in enumerate(resume.get("skills") or []):
        if isinstance(skill, str) and skill.strip():
            out.append((f"skills[{i}]", " ".join(skill.split())))
    for j, job in enumerate(resume.get("experience") or []):
        for k, bullet in enumerate((job or {}).get("bullets") or []):
            if str(bullet).strip():
                out.append((f"experience[{j}].bullets[{k}]", " ".join(str(bullet).split())))
    for i, seg in enumerate(p.strip() for p in str(resume.get("headline") or "").split("|") if p.strip()):
        out.append((f"headline[{i}]", seg))
    for i, sentence in enumerate(_sentences(str(resume.get("summary") or ""))):
        out.append((f"summary[{i}]", " ".join(sentence.split())))
    return out


def job_review(resume: dict, result: dict, facts: dict, now=None) -> dict:
    """The member review of a job-targeted résumé, built from the job pipeline's OWN records (its term report, claim and verb review,
    struck claims, removed skills and held lines). Nothing is classified here that the pipeline did not record, except by the exact-match
    rule against the member's saved information. Statements the pipeline left unresolved stay UNCERTAIN for the member to decide."""
    result = result or {}
    terms = {}
    for t in result.get("term_report") or []:
        if isinstance(t, dict) and t.get("term"):
            terms.setdefault(_norm_words(t["term"]), t)
    unresolved = set()
    for key in ("claim_review", "verb_review", "fact_verb_review"):
        for x in result.get(key) or []:
            if isinstance(x, dict) and x.get("text"):
                unresolved.add(_norm_words(x["text"]))
    saved_sentences = [sent for _, text in _source_refs(facts) for sent in _statement_units(text)]
    skill_keys = {_norm_words(sk) for sk in facts.get("skills") or [] if sk}
    saved_facts = ([c.get("name", "") for c in facts.get("certifications") or [] if c.get("name")]
                   + [e.get("degree", "") for e in facts.get("education") or [] if e.get("degree")]
                   + [r.get("title", "") for r in facts.get("roles") or [] if r.get("title")])
    findings, supported, derived = [], [], []
    for where, text in statements(resume):
        key = _norm_words(text)
        term = terms.get(key) if where.startswith("skills[") else None
        if term is not None and term.get("support") in _PIPELINE_SUPPORTED:
            supported.append({"where": where, "text": text, "classification": "SUPPORTED",
                              "source": f'job term "{term.get("term")}": {term.get("evidence") or "found in your saved information"}',
                              "explanation": "The job checks found this in your saved information."})
            continue
        if term is not None and term.get("support") == _PIPELINE_TRANSFERABLE:
            derived.append({"where": where, "text": text, "classification": "DERIVED",
                            "source": f'a different activity in your saved information: {term.get("evidence") or ""}'.strip(),
                            "explanation": "A real activity in your saved information builds this skill. The wording is the job's own."})
            continue
        exact = _exact_saved_statement(text, saved_sentences, saved_facts)
        if exact is not None and key not in unresolved:
            supported.append({"where": where, "text": text, "classification": "SUPPORTED", "source": exact,
                              "explanation": "Matches your saved information exactly."})
            continue
        explanation = ("The job checks could not confirm this wording from your saved information. Keep it only if it is true for you, "
                       "change it, or remove it.") if key in unresolved else (
                       "Not an exact match to your saved information. Confirm the statement is true for you before it is used.")
        if where.startswith("headline") and key in skill_keys:
            explanation = HEADLINE_SKILL_EXPLANATION    # F3: a saved skill does not justify the same words as a headline
        findings.append({"where": where, "text": text, "classification": "UNCERTAIN", "source": None, "explanation": explanation})
    removed = []
    for skill in result.get("skills_removed") or []:
        removed.append({"where": "skills", "text": str(skill),
                        "explanation": "Removed: the job checks found no basis for this skill in your saved information."})
    for claim in result.get("claims_struck") or []:
        if isinstance(claim, dict):
            removed.append({"where": str(claim.get("where", "")), "text": str(claim.get("text", "")),
                            "explanation": str(claim.get("reason") or "Removed: not supported by your saved information.")})
    for held in result.get("lines_held") or []:
        if isinstance(held, dict):
            removed.append({"where": str(held.get("where", "")), "text": str(held.get("text", "")),
                            "explanation": "Held out of the résumé until you confirm the wording in your saved information."})
    return {"checker_version": JOB_CHECKER, "mode": "on", "source": "job_pipeline",
            "content_hash": content_hash(resume), "facts_hash": facts_hash(facts),
            "items": _items_from(findings), "removed": removed, "supported": supported, "derived": derived,
            "receipts": [], "edits": [], "created_at": (now or datetime.now(timezone.utc)).isoformat()}


def apply_edit(draft: dict, facts: dict, review: dict, item_id: str, new_text, user_id: int, now=None, kind: str = "general"):
    """The Edit decision, revalidated on the server. Returns (new_draft, new_review, status, message) where status is None on success.

    The edited wording is checked against the saved facts like any other statement. It is never SUPPORTED on the member's word:
    if it is UNSUPPORTED it is refused; if it is UNCERTAIN it needs its own decision. Its new text has a new identity, so no earlier
    Keep or sign-off carries over to it. Other statements keep their decisions. Any edit clears the sign-off."""
    item = next((i for i in review.get("items", []) if i["id"] == item_id), None)
    if item is None:
        return None, None, 404, "That statement is not part of this résumé."
    if not decidable(item):
        return None, None, 409, "Only an uncertain statement in the résumé text can be edited."
    text = " ".join(str(new_text or "").split())
    if not text:
        return None, None, 400, "Write the statement you want, or choose Remove."
    if len(text) > EDIT_MAX_LENGTH:
        return None, None, 400, "Keep the statement under 300 characters."
    if "|" in text and item["where"].startswith("headline"):
        return None, None, 400, "Write one headline phrase without the '|' character."
    if text == item["text"]:
        return None, None, 400, "The wording has not changed. Choose Keep to confirm it, or change the wording."
    try:
        new_draft = replace_statement(draft, item["where"], item["text"], text)
    except ValueError:
        return None, None, 409, "This statement has changed. Check the résumé again."
    checked = [f for f in general_truth_findings(new_draft, facts) if f["where"] == item["where"] and f["text"] == text]
    edited = checked[0] if checked else None
    if edited is not None and edited["classification"] == "UNSUPPORTED":
        return None, None, 409, ("This wording is not supported by your saved information. Change it to match what you have "
                                 "actually done, or choose Remove.")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    edits = list(review.get("edits") or []) + [{"where": item["where"], "old_text": item["text"], "new_text": text,
                                                 "by": user_id, "at": stamp}]
    if kind == "job":
        # The job's own items keep their identity and decisions; only the edited statement is classified afresh (by the checker, on its
        # new wording). A SUPPORTED wording is recorded as supported, an UNCERTAIN one needs its own decision.
        new_items = [i for i in review.get("items", []) if i["id"] != item["id"]]
        supported = list(review.get("supported") or [])
        if edited is None or edited["classification"] == "UNCERTAIN":
            # no finding is never a free pass: a wording the checker did not classify needs the member's own decision
            new_items += _items_from([edited or {"where": item["where"], "text": text, "classification": "UNCERTAIN", "source": None,
                                               "explanation": "Not an exact match to your saved information. Confirm the statement is true for you before it is used."}])
        elif edited is not None and edited["classification"] == "SUPPORTED":
            supported.append({"where": edited["where"], "text": text, "classification": "SUPPORTED", "source": edited.get("source"),
                              "explanation": edited.get("explanation")})
        new_review = {**review, "content_hash": content_hash(new_draft), "items": new_items, "supported": supported,
                      "receipts": [], "edits": edits[-50:]}
        return new_draft, new_review, None, None
    new_items = _items_from(general_truth_findings(new_draft, facts))
    stored = {i["id"]: i for i in review.get("items", [])}
    for ni in new_items:
        prev = stored.get(ni["id"])
        if prev is not None:   # an unchanged statement keeps its decision; the edited one has a new identity and none
            ni.update({k: prev.get(k) for k in ("decision", "acknowledged", "decided_at", "decided_by")})
    new_review = {**review, "content_hash": content_hash(new_draft), "items": new_items, "receipts": [], "edits": edits[-50:]}
    return new_draft, new_review, None, None


def apply_removals(resume: dict, wheres) -> dict:
    """A copy of the résumé with the named statements removed. Indices refer to the same résumé the checker was run on."""
    out = copy.deepcopy(resume or {})
    skill_rm, bullet_rm, head_rm, sum_rm, cert_rm = set(), set(), set(), set(), set()
    for where in wheres:
        if not _REMOVABLE.match(where):
            continue
        m = re.fullmatch(r"skills\[(\d+)\]", where)
        if m:
            skill_rm.add(int(m.group(1)))
            continue
        m = re.fullmatch(r"experience\[(\d+)\]\.bullets\[(\d+)\]", where)
        if m:
            bullet_rm.add((int(m.group(1)), int(m.group(2))))
            continue
        m = re.fullmatch(r"headline\[(\d+)\]", where)
        if m:
            head_rm.add(int(m.group(1)))
            continue
        m = re.fullmatch(r"summary\[(\d+)\]", where)
        if m:
            sum_rm.add(int(m.group(1)))
            continue
        m = re.fullmatch(r"certifications\[(\d+)\]", where)
        if m:
            cert_rm.add(int(m.group(1)))
    if skill_rm and isinstance(out.get("skills"), list):
        out["skills"] = [s for i, s in enumerate(out["skills"]) if i not in skill_rm]
    if bullet_rm:
        for j, job in enumerate(out.get("experience") or []):
            if isinstance(job.get("bullets"), list):
                job["bullets"] = [b for k, b in enumerate(job["bullets"]) if (j, k) not in bullet_rm]
    if head_rm and out.get("headline"):
        segs = [p.strip() for p in str(out["headline"]).split("|") if p.strip()]
        out["headline"] = " | ".join(s for i, s in enumerate(segs) if i not in head_rm)
    if sum_rm and out.get("summary"):
        sents = _sentences(str(out["summary"]))
        out["summary"] = " ".join(s for i, s in enumerate(sents) if i not in sum_rm)
    if cert_rm and isinstance(out.get("certifications"), list):
        out["certifications"] = [c for i, c in enumerate(out["certifications"]) if i not in cert_rm]
    return out


def _item_id(where: str, text: str) -> str:
    return hashlib.sha256(f"{where}|{text}".encode("utf-8")).hexdigest()[:16]


def _items_from(findings) -> list[dict]:
    items = []
    for f in findings:
        if f["classification"] in ("SUPPORTED", "DERIVED"):
            continue
        items.append({"id": _item_id(f["where"], f["text"]), "where": f["where"], "classification": f["classification"],
                      "text": f["text"], "source": f.get("source"), "explanation": f["explanation"],
                      "decision": None, "acknowledged": False, "decided_at": None, "decided_by": None})
    return items


def review_at_save(resume: dict, facts: dict, mode: str, now=None):
    """Returns (draft_resume, truth_review). In "on", unsupported removable statements are removed before the draft is stored."""
    first = general_truth_findings(resume, facts)
    removed = [{"where": f["where"], "text": f["text"], "explanation": f["explanation"]}
               for f in first if f["classification"] == "UNSUPPORTED" and _REMOVABLE.match(f["where"])]
    draft = apply_removals(resume, [r["where"] for r in removed]) if mode == "on" else copy.deepcopy(resume)
    findings = general_truth_findings(draft, facts)   # indices of the stored draft
    review = {
        "checker_version": CHECKER_VERSION, "mode": mode,
        "content_hash": content_hash(draft), "facts_hash": facts_hash(facts),
        "items": _items_from(findings), "removed": removed, "receipts": [],
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    return draft, review


def decidable(item: dict) -> bool:
    return item["classification"] == "UNCERTAIN" and bool(_REMOVABLE.match(item["where"]) or item["where"].startswith("headline"))


def validate_decision(review: dict, item_id: str, decision: str, acknowledge: bool):
    """Returns (status_code, message). (None, None) when the decision may be recorded."""
    item = next((i for i in review.get("items", []) if i["id"] == item_id), None)
    if item is None:
        return 404, "That statement is not part of this résumé."
    if item["classification"] == "UNSUPPORTED":
        return 409, ("This statement is not supported by your saved information, so it cannot be confirmed. "
                     "Correct your saved information first, then check the résumé again.")
    if decision not in ("keep", "remove"):
        return 400, "Choose Keep or Remove."
    if decision == "keep" and not acknowledge:
        return 400, "Confirm that you have read this statement and that it is true for you before keeping it."
    if decision == "remove" and not decidable(item):
        return 409, "This line belongs to a saved entry. Correct the entry in your saved information instead."
    return None, None


def record_decision(review: dict, item_id: str, decision: str, acknowledge: bool, user_id: int, now=None) -> dict:
    out = copy.deepcopy(review)
    item = next(i for i in out["items"] if i["id"] == item_id)
    item.update({"decision": decision, "acknowledged": bool(acknowledge) if decision == "keep" else False,
                 "decided_at": (now or datetime.now(timezone.utc)).isoformat(), "decided_by": user_id})
    return out


def finalize(draft: dict, review: dict) -> dict:
    """The content the member signs off: the draft with every statement the member chose to remove taken out."""
    remove = [i["where"] for i in review.get("items", []) if i["classification"] == "UNCERTAIN" and i.get("decision") == "remove"]
    return apply_removals(draft, remove)


def evidence(draft: dict, facts: dict) -> dict:
    """What the member's saved information supports, for the review screen: SUPPORTED statements with their saved source, and
    DERIVED skills with the evidence they come from. Read-only; nothing here is a decision."""
    rows = [{"where": f["where"], "text": f["text"], "classification": f["classification"], "source": f.get("source"),
             "explanation": f["explanation"]} for f in general_truth_findings(draft, facts)
            if f["classification"] in ("SUPPORTED", "DERIVED")]
    return {"supported": [r for r in rows if r["classification"] == "SUPPORTED"],
            "derived": [r for r in rows if r["classification"] == "DERIVED"]}


def pending(review: dict, draft: dict, facts: dict, kind: str = "general"):
    """(blocking, undecided): statements that cannot be confirmed, and uncertain statements with no decision yet. A general review is
    recomputed now; a job review's items are the job pipeline's own records (kept as stored; the content and facts hashes guarantee
    they still match the résumé)."""
    if kind == "job":
        items = review.get("items", [])
        return ([i for i in items if i["classification"] == "UNSUPPORTED"],
                [i for i in items if i["classification"] == "UNCERTAIN" and i.get("decision") is None])
    fresh = _items_from(general_truth_findings(draft, facts))
    stored = {i["id"]: i for i in review.get("items", [])}
    blocking = [i for i in fresh if i["classification"] == "UNSUPPORTED"]
    undecided = [i for i in fresh if i["classification"] == "UNCERTAIN" and (stored.get(i["id"], {}).get("decision") is None)]
    return blocking, undecided


def docx_text(data: bytes) -> str:
    """Text of a DOCX body, one line per paragraph (used to check the rendered output against what was signed)."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(f"{ns}p"):
        lines.append("".join(t.text or "" for t in p.iter(f"{ns}t")))
    return "\n".join(lines)


def rendered_hash(data: bytes) -> str:
    return hashlib.sha256(docx_text(data).encode("utf-8")).hexdigest()
