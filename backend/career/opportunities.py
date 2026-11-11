"""My Opportunities (C-52 MVP-0): job links the member saves, compared with their own profile, with a résumé approved for that job
and an application recorded in the existing tracker.

Specification: C-52 revision 2 (MVP0-SPEC-REV2_2026-11-09). Implementation note: docs/C52-IMPLEMENTATION-NOTE.md.

Feature switch: CT_OPPORTUNITIES_ENABLED (default off). When off, every route answers 404.
This module never fetches a saved link, never calls an AI service, and never makes an outbound network call.
"""
import hashlib
import ipaddress
import json
import os
import re
import unicodedata
from datetime import date, datetime  # noqa: F401  (datetime kept for type readers)
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictInt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from career.routes import ApplicationIn, _application_to_dict, _preferred_layout, _validated_application_fields, get_career_profile_or_404
from db import get_db_session
from limits import Long, Short, Tiny
from models import Application, CareerProfile, Opportunity, ResumeVersion, User


def require_enabled() -> None:
    if os.environ.get("CT_OPPORTUNITIES_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=404, detail="Not found.")


router = APIRouter(dependencies=[Depends(require_enabled)])

MAX_PER_MEMBER = 200
MAX_URL_CHARS = 2000
WORK_ARRANGEMENTS = ("remote", "hybrid", "on_site")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "temporary", "internship", "other")
BASE_PERIODS = ("hourly", "annual")
DISMISS_REASONS = ("not_interested", "wrong_location", "pay_too_low", "looks_suspicious", "other")
SETTABLE_STATES = ("saved", "dismissed")   # 'applied' comes only from record-application
MAX_PAY = 10_000_000
# Tracking parameters removed for the duplicate key only. src and refid are NOT removed: some job boards use them to identify
# the posting, so removing them could merge two distinct jobs (C-52 correction F03).
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|trk.*|trackingid)$", re.IGNORECASE)
UNSUPPORTED_ADDRESS = "This web address isn’t supported yet. Please enter a standard HTTPS job link."
# Bumped by hand whenever backend/resume_builder.py changes how a résumé is drawn. The approval fingerprint includes it, so a
# renderer change cannot leave an old approval reading "current". Not automatic: maintainers must bump it with such a change.
RENDER_FINGERPRINT = "resume-builder-2026-11-11"
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMERIC_LABEL = re.compile(r"^(0[xX][0-9a-fA-F]*|[0-9]+)$")   # decimal, octal or hex label: an IPv4 part in another notation
URL_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f\s]")   # no spaces, no control characters inside a link
BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".test", ".invalid", ".home", ".lan")
SOURCE_LABELS = (("linkedin.com", "LinkedIn (saved by you)"), ("indeed.com", "Indeed (saved by you)"), ("usajobs.gov", "USAJOBS"))
DEFAULT_SOURCE = "Employer or other site (saved by you)"


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def normalize_job_url(raw: object) -> tuple[str, str]:
    """Returns (stored_url, dedupe_key). Refuses anything that is not a plain https link to a public name. Never fetches."""
    if not isinstance(raw, str):
        raise _bad("Please enter the job link.")
    url = raw.strip()
    if not url or len(url) > MAX_URL_CHARS:
        raise _bad("The job link must be between 1 and 2000 characters.")
    if URL_FORBIDDEN.search(url):
        raise _bad("The job link contains spaces or hidden characters. Paste it again.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise _bad("That does not look like a web link.")
    if parts.scheme.lower() != "https":
        raise _bad("Only secure (https) links can be saved.")
    if "@" in parts.netloc or parts.username or parts.password:
        raise _bad("Links with a username or password are not accepted.")
    host = (parts.hostname or "").lower()
    if not host:
        raise _bad("That link does not have a readable web address.")
    # Unicode host names and percent-encoded host names are not supported in MVP-0 (the browser would decode them to a
    # different name than the one stored for duplicate checking). Punycode (xn--) names are plain ASCII and are accepted.
    if not host.isascii() or "%" in host:
        raise _bad(UNSUPPORTED_ADDRESS)
    # A trailing dot ("localhost.", "127.0.0.1.") or an empty label is refused outright, never silently trimmed.
    if host.endswith(".") or ".." in host or host.startswith("."):
        raise _bad("That address is not a public website. Paste the employer's or site's public link.")
    # A last label that is decimal, octal or hex (0x7f, 0X1, 0177) makes the whole host an IPv4 address in some other
    # notation, which browsers normalise (0x7f.0x0.0x0.0x1 is 127.0.0.1). Refuse those hosts.
    if "." not in host or host == "localhost" or host.endswith(BLOCKED_SUFFIXES) or _is_ip(host.strip("[]")) or NUMERIC_LABEL.match(host.rsplit(".", 1)[-1]):
        raise _bad("That address is not a public website. Paste the employer's or site's public link.")
    if port not in (None, 443):
        raise _bad("Only standard secure (https) links can be saved.")
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)))
    canonical = "https://" + host + path + (("?" + query) if query else "")
    return url, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clean_text(value: object, limit: int, field: str, required: bool = False, multiline: bool = False) -> str | None:
    if value is None:
        if required:
            raise _bad(f"Please enter the {field}.")
        return None
    if not isinstance(value, str):
        raise _bad(f"The {field} must be text.")
    text = value.strip()
    if not text:
        if required:
            raise _bad(f"Please enter the {field}.")
        return None
    if len(text) > limit:
        raise _bad(f"The {field} is too long.")
    for ch in text:
        if unicodedata.category(ch) == "Cc" and not (multiline and ch in "\n\t"):
            raise _bad(f"The {field} contains hidden characters. Please retype it.")
    return text


def _check_pay(base_min, base_max, base_period, pay_note):
    for name, v in (("base_min", base_min), ("base_max", base_max)):
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > MAX_PAY):
            raise _bad("Guaranteed base pay must be a whole number between 0 and 10,000,000.")
    if base_min is not None and base_max is not None and base_min > base_max:
        raise _bad("The lowest base pay is higher than the highest.")
    if (base_min is not None or base_max is not None):
        if base_period not in BASE_PERIODS:
            raise _bad("Choose whether the base pay is per hour or per year.")
    elif base_period is not None:
        raise _bad("Enter a base pay amount, or leave the period empty.")
    return _clean_text(pay_note, 300, "other pay note")


def _source_label(stored_url: str) -> str:
    host = (urlsplit(stored_url).hostname or "").lower()
    for domain, label in SOURCE_LABELS:
        if host == domain or host.endswith("." + domain):
            return label
    return DEFAULT_SOURCE


def _real_date(value: str) -> bool:
    """YYYY-MM-DD and an actual calendar day (2026-02-31 and 2026-13-01 are refused)."""
    if not ISO_DATE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _output_fingerprint(db: Session, v: ResumeVersion) -> str:
    """What the approval is for: the version's content AND the layout the downloaded DOCX is drawn with (the saved profile
    layout, which is the download default). Profile settings unrelated to the rendering are not part of it.
    Other inputs to the document, checked for C-52 F02:
      - ats_mode: a download-time option, not stored. An approval covers the default (visual) rendering only; an ATS-mode
        download is a different file and is not covered by the approval.
      - template query parameter: a download-time override. Same limitation as ats_mode.
      - document properties (created, modified, author): set to the download time by the renderer. Not part of the
        approval; the body text and styles are.
      - renderer code: covered by RENDER_FINGERPRINT (manual).
    """
    profile = db.get(CareerProfile, v.career_profile_id)
    layout = _preferred_layout(db, profile) if profile is not None else "classic"
    # Approved rendering = the visual (not ATS) document in the saved layout. The mode and template are stated here so that a
    # change to either is part of the approval. An ATS-mode or other-template download is a different file and is not approved.
    payload = {"resume_data": v.resume_data or {}, "layout": layout, "template": layout, "ats_mode": False, "renderer": RENDER_FINGERPRINT}
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class OpportunityIn(BaseModel):
    # The version the card was showing (from GET or the last save). A details save is refused if the link changed since.
    if_version: Tiny | None = None
    title: Short
    employer: Short | None = None
    job_url: str
    location_text: Short | None = None
    work_arrangement: Tiny | None = None
    employment_type: Tiny | None = None
    base_min: StrictInt | None = None
    base_max: StrictInt | None = None
    base_period: Tiny | None = None
    pay_note: Short | None = None
    notes: Long | None = None
    state: Tiny | None = None
    dismiss_reason: Tiny | None = None
    last_verified_on: Tiny | None = None
    follow_up_on: Tiny | None = None


class RecordIn(BaseModel):
    applied_on: Tiny | None = None


def _owned(db: Session, profile: CareerProfile, opportunity_id: int, lock: bool = False) -> Opportunity:
    q = db.query(Opportunity).filter_by(id=opportunity_id, career_profile_id=profile.id)
    if lock:
        q = q.with_for_update()
    row = q.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Saved job not found.")
    return row


def _approval(db: Session, o: Opportunity) -> dict | None:
    if o.approved_resume_version_id is None:
        return None
    v = db.get(ResumeVersion, o.approved_resume_version_id)
    if v is None or v.career_profile_id != o.career_profile_id:
        return {"version_id": o.approved_resume_version_id, "status": "version_removed"}
    if _output_fingerprint(db, v) != o.approved_resume_hash:
        return {"version_id": v.id, "status": "changed_since_approval"}
    return {"version_id": v.id, "status": "current"}


STALE_MESSAGE = ("This saved link was changed in another tab or window, so your change was not saved. "
                 "Reload the page to see the latest details, then make the change again.")


def _version(o: Opportunity) -> str:
    """A token for the link's current stored content, including its approval and application link. Content-based, so it
    works the same on SQLite and PostgreSQL (no timestamp resolution issue) and needs no new column."""
    fields = {
        "title": o.title, "employer": o.employer, "job_url": o.job_url, "location_text": o.location_text,
        "work_arrangement": o.work_arrangement, "employment_type": o.employment_type, "base_min": o.base_min,
        "base_max": o.base_max, "base_period": o.base_period, "pay_note": o.pay_note, "state": o.state,
        "dismiss_reason": o.dismiss_reason, "last_verified_on": o.last_verified_on, "notes": o.notes,
        "follow_up_on": o.follow_up_on, "application_id": o.application_id,
        "approved_resume_version_id": o.approved_resume_version_id, "approved_resume_hash": o.approved_resume_hash,
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]


def _to_dict(db: Session, o: Opportunity) -> dict:
    app_exists = False
    if o.application_id is not None:
        app = db.get(Application, o.application_id)
        app_exists = app is not None and app.career_profile_id == o.career_profile_id
    effective = o.state
    removed = False
    if o.state == "applied":
        if app_exists:
            effective = "applied"
        else:
            effective = "saved"       # the linked application was deleted: shown as saved, with a flag; stored data is not rewritten
            removed = True
    base = None
    if o.base_min is not None or o.base_max is not None:
        base = {"min": o.base_min, "max": o.base_max, "period": o.base_period}
    return {
        "id": o.id, "title": o.title, "employer": o.employer, "job_url": o.job_url, "source": _source_label(o.job_url),
        "location_text": o.location_text, "work_arrangement": o.work_arrangement, "employment_type": o.employment_type,
        "base": base, "base_note": "Guaranteed base pay as you entered it. Other pay is never counted as base.",
        "pay_note": o.pay_note, "state": effective, "dismiss_reason": o.dismiss_reason,
        "application_removed": removed, "application_id": o.application_id if app_exists else None,
        "last_verified_on": o.last_verified_on, "notes": o.notes, "follow_up_on": o.follow_up_on,
        "approval": _approval(db, o),
        "version": _version(o),
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
        "safety_notice": ("Creating Tomorrow does not endorse employers or guarantee the authenticity of listings. "
                          "Verify opportunities through the employer's official website before sharing sensitive information. "
                          "Never pay to apply for a job or receive a job offer."),
    }


def _application_still_linked(db: Session, profile: CareerProfile, o: Opportunity) -> bool:
    if o.application_id is None:
        return False
    app = db.get(Application, o.application_id)
    return app is not None and app.career_profile_id == profile.id


def _apply_fields(db: Session, profile: CareerProfile, o: Opportunity, req: OpportunityIn, creating: bool) -> None:
    o.title = _clean_text(req.title, 300, "job title", required=True)
    o.employer = _clean_text(req.employer, 300, "employer")
    url, key = normalize_job_url(req.job_url)
    if creating or key != o.dedupe_key:
        clash = db.query(Opportunity).filter_by(career_profile_id=profile.id, dedupe_key=key).one_or_none()
        if clash is not None and clash.id != o.id:
            raise HTTPException(status_code=409, detail={"message": "You have already saved this link.", "existing_id": clash.id})
    o.job_url, o.dedupe_key = url, key
    o.location_text = _clean_text(req.location_text, 300, "location")
    if req.work_arrangement is not None and req.work_arrangement not in WORK_ARRANGEMENTS:
        raise _bad("Choose remote, hybrid or on-site.")
    if req.employment_type is not None and req.employment_type not in EMPLOYMENT_TYPES:
        raise _bad("That employment type is not one of the options.")
    o.work_arrangement, o.employment_type = req.work_arrangement, req.employment_type
    o.base_min, o.base_max, o.base_period = req.base_min, req.base_max, req.base_period
    o.pay_note = _check_pay(req.base_min, req.base_max, req.base_period, req.pay_note)
    o.notes = _clean_text(req.notes, 2000, "notes", multiline=True)
    if req.last_verified_on is not None and not _real_date(req.last_verified_on):
        raise _bad("Enter the date you checked the link as a valid date.")
    if req.follow_up_on is not None and not _real_date(req.follow_up_on):
        raise _bad("Enter the follow-up date as a valid date.")
    o.last_verified_on, o.follow_up_on = req.last_verified_on, req.follow_up_on
    # The résumé approval is NOT set here. It changes only through PUT /opportunities/{id}/approval, so a details edit (with or
    # without the approval field) can never clear or replace an approval, and cannot be refused because of one.
    # state: only saved or dismissed can be set here
    if req.state is not None:
        if req.state not in SETTABLE_STATES:
            raise _bad("That state cannot be set here. Recording an application is a separate step.")
        if o.state == "applied" and req.state != "applied":
            raise _bad("This job already has an application recorded. Remove it from the tracker first.")
        o.state = req.state
    elif creating:
        o.state = "saved"
    if o.state == "dismissed":
        if req.dismiss_reason is not None and req.dismiss_reason not in DISMISS_REASONS:
            raise _bad("That reason is not one of the options.")
        o.dismiss_reason = req.dismiss_reason or "other"
    else:
        o.dismiss_reason = None


@router.get("/opportunities")
async def list_opportunities(state: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    rows = db.query(Opportunity).filter_by(career_profile_id=profile.id).order_by(Opportunity.created_at.desc(), Opportunity.id.desc()).all()
    out = [_to_dict(db, o) for o in rows]
    if state is not None:
        if state not in ("saved", "dismissed", "applied"):
            raise _bad("That list is not one of the options.")
        out = [o for o in out if o["state"] == state]
    return out


@router.post("/opportunities")
async def create_opportunity(req: OpportunityIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    # Serialise saves for one member: lock the profile row, then count. On PostgreSQL concurrent saves wait here,
    # so the 200-link cap cannot be exceeded. (SQLite ignores FOR UPDATE; tests cover the SQL, not the race.)
    db.query(CareerProfile).filter_by(id=profile.id).with_for_update().one()
    count = db.query(Opportunity).filter_by(career_profile_id=profile.id).count()
    if count >= MAX_PER_MEMBER:
        raise HTTPException(status_code=409, detail=f"You have {MAX_PER_MEMBER} saved links. Delete or dismiss some first.")
    o = Opportunity(career_profile_id=profile.id)
    try:
        _apply_fields(db, profile, o, req, creating=True)
        db.add(o)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"message": "You have already saved this link."})
    except Exception:
        db.rollback()
        raise
    db.refresh(o)
    return _to_dict(db, o)


@router.put("/opportunities/{opportunity_id}")
async def update_opportunity(opportunity_id: int, req: OpportunityIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    o = _owned(db, profile, opportunity_id, lock=True)  # serialised with record-application
    if req.if_version is not None and req.if_version != _version(o):
        db.rollback()   # nothing changed; releases the lock
        raise HTTPException(status_code=409, detail={"message": STALE_MESSAGE})
    try:
        _apply_fields(db, profile, o, req, creating=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(o)
    return _to_dict(db, o)


class ApprovalIn(BaseModel):
    approved_resume_version_id: StrictInt | None = None


@router.put("/opportunities/{opportunity_id}/approval")
async def set_approval(opportunity_id: int, req: ApprovalIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    """Changes only the approved résumé version of one saved link. Every other field is left exactly as stored, so a
    client holding an old copy of the link cannot overwrite newer details. Refused once an application is recorded."""
    profile = get_career_profile_or_404(db, current_user)
    try:
        o = _owned(db, profile, opportunity_id, lock=True)   # serialised with record-application and other edits
        if req.approved_resume_version_id is None and o.approved_resume_version_id is None:
            db.rollback()                                    # nothing to change; releases the lock
            return _to_dict(db, o)
        if req.approved_resume_version_id == o.approved_resume_version_id and o.approved_resume_version_id is not None:
            same = db.query(ResumeVersion).filter_by(id=o.approved_resume_version_id, career_profile_id=profile.id).one_or_none()
            if same is not None and _output_fingerprint(db, same) == o.approved_resume_hash:
                db.rollback()                                # still current: nothing to change; releases the lock
                return _to_dict(db, o)
            # same version, but the approval is stale (content or layout changed): approving again refreshes it
        if _application_still_linked(db, profile, o):
            raise HTTPException(status_code=409, detail="An application is already recorded for this job, so its résumé approval cannot change. The application keeps the résumé it was recorded with.")
        if req.approved_resume_version_id is None:
            o.approved_resume_version_id, o.approved_resume_hash = None, None
        else:
            v = db.query(ResumeVersion).filter_by(id=req.approved_resume_version_id, career_profile_id=profile.id).one_or_none()
            if v is None:
                raise _bad("That résumé no longer exists.")
            o.approved_resume_version_id, o.approved_resume_hash = v.id, _output_fingerprint(db, v)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(o)
    return _to_dict(db, o)


@router.delete("/opportunities/{opportunity_id}")
async def delete_opportunity(opportunity_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    o = _owned(db, profile, opportunity_id)
    db.delete(o)   # the tracker entry, if any, is kept: it is a separate record
    db.commit()
    return {"deleted": True}


@router.delete("/opportunities")
async def clear_dismissed(state: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    if state != "dismissed":
        raise _bad("Only dismissed links can be cleared in one step.")
    profile = get_career_profile_or_404(db, current_user)
    n = db.query(Opportunity).filter_by(career_profile_id=profile.id, state="dismissed").delete(synchronize_session=False)
    db.commit()
    return {"deleted": n}


@router.post("/opportunities/{opportunity_id}/record-application")
async def record_application(opportunity_id: int, req: RecordIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    """One transaction. Retry-safe: if this job already links to an application, that application is returned and nothing new is written."""
    profile = get_career_profile_or_404(db, current_user)
    try:
        o = _owned(db, profile, opportunity_id, lock=True)
        if o.application_id is not None:
            existing = db.get(Application, o.application_id)
            if existing is not None and existing.career_profile_id == profile.id:
                db.rollback()   # nothing was changed; releases the lock
                return {"already_recorded": True, "opportunity": _to_dict(db, o), "application": _application_to_dict(existing)}
        if req.applied_on and not _real_date(req.applied_on.strip()):
            raise _bad("Enter the date you applied as a valid date.")
        if o.state == "dismissed":
            raise HTTPException(status_code=409, detail="Restore this job before recording an application.")
        # A résumé must be approved for this job, and the approval must still be current, before an application is recorded.
        if o.approved_resume_version_id is None:
            raise HTTPException(status_code=409, detail="Approve a résumé for this saved job before recording the application.")
        # Lock the approved version before reading its fingerprint: an edit, suggestion or deletion on this version waits
        # for this transaction, and cannot change the content between the approval check and the application record.
        db.query(ResumeVersion).filter_by(id=o.approved_resume_version_id).with_for_update().first()
        approval = _approval(db, o)
        if approval["status"] == "version_removed":
            raise HTTPException(status_code=409, detail="The résumé you approved for this job was removed. Approve a résumé, then record the application.")
        if approval["status"] != "current":
            raise HTTPException(status_code=409, detail="The résumé you approved for this job has changed since you approved it. Approve it again, then record the application.")
        resume_id = approval["version_id"]
        fields = _validated_application_fields(db, profile, ApplicationIn(
            job_title=o.title, company=o.employer, applied_on=req.applied_on, status="applied", resume_version_id=resume_id))
        app = Application(career_profile_id=profile.id, **fields)
        db.add(app)
        db.flush()                       # gives the application its id inside the same transaction
        o.application_id = app.id
        o.state = "applied"
        o.dismiss_reason = None
        db.commit()                      # both rows, or neither
    except Exception:
        db.rollback()
        raise
    db.refresh(o)
    db.refresh(app)
    return {"already_recorded": False, "opportunity": _to_dict(db, o), "application": _application_to_dict(app)}
