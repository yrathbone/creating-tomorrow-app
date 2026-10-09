"""
/api/career/* endpoints - Account and Career Profile/Manual-CRUD phases
(docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md Decision 4's locked sequence).

Every route here follows Deliverable E's ownership rule: the acting user
is derived exclusively from the verified Cognito token
(Depends(get_current_user)) - never from a path parameter, query string,
or request body. get_career_profile_or_404() is the one place that looks
up "whose Career Profile is this," so no route hand-rolls its own
ownership filter.

Consent gating follows Deliverable F: consent_given_at and the
CareerProfile row are both set together, only by an explicit POST to
/consent - no Career Profile data can exist before that, since there's no
CareerProfile row yet for a child row to attach to.
"""
import base64
import logging
import re
from contextlib import contextmanager
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from career.ingestion import IngestionError, discover, ElevateError, start_resume_review
from career.job_match import JobMatchError, build_general_resume, compare_to_job
from career.job_fit import compute_job_fit
from career.linkedin_compare import compare_roles, compare_skills
from career.term_pipeline import build_checked_resume, dedupe_skills, keyword_check, suggest_skill_keywords, tidy_candidates
from career.skill_scan import SkillScanError, start_skill_scan
from db import get_db_session
from extractor import extract_text
from models import Application, CareerProfile, Certification, Education, Experience, Language, ResumeIngestionDraft, ResumeVersion, ScanHistory, Skill, User
from download_names import attachment_headers
from profile_copy import build_profile_copy_bytes
from resume_builder import build_resume_bytes

router = APIRouter()

logger = logging.getLogger(__name__)

_MISSING_SCHEMA_HINTS = ("no such table", "no such column", "does not exist", "undefinedtable", "undefinedcolumn")


@contextmanager
def schema_upgrade_guard(db: Session, what: str, migration: str = "0008"):
    """Migrations 0008 (languages table, display_name/contact_line) and 0009 (preferred resume layout)
    are applied by hand (`alembic upgrade head`). Until then these features must say so plainly instead of
    failing mysteriously or pretending to work: a missing table/column becomes a logged
    503 naming what is not upgraded. Any other database error is re-raised untouched."""
    try:
        yield
    except (OperationalError, ProgrammingError) as e:
        db.rollback()
        if any(h in str(e).lower() for h in _MISSING_SCHEMA_HINTS):
            logger.error("Database schema not upgraded for %s (run `alembic upgrade head`): %s", what, e.__class__.__name__)
            raise HTTPException(
                status_code=503,
                detail=f"{what} are not available yet: the database upgrade (migration {migration}) has not been applied.",
            ) from e
        raise

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB - matches main.py's existing resume-upload limit
MAX_PDF_UPLOAD_BYTES = 20 * 1024 * 1024  # a LinkedIn page printed to PDF is pictures of pages, so it is large


def get_career_profile_or_404(db: Session, current_user: User) -> CareerProfile:
    profile = db.query(CareerProfile).filter_by(user_id=current_user.id).one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="No Career Profile yet - consent (POST /api/career/consent) is required first.",
        )
    return profile


@router.get("/me")
async def career_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "consent_given": current_user.consent_given_at is not None,
    }


@router.post("/consent")
async def give_consent(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if current_user.consent_given_at is None:
        current_user.consent_given_at = datetime.now(timezone.utc)
        db.add(current_user)

    profile = db.query(CareerProfile).filter_by(user_id=current_user.id).one_or_none()
    if profile is None:
        profile = CareerProfile(user_id=current_user.id)
        db.add(profile)

    db.commit()
    db.refresh(profile)
    return {"consent_given": True, "career_profile_id": profile.id}


class ExperienceIn(BaseModel):
    title: str
    organization: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


def _experience_to_dict(e: Experience) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "organization": e.organization,
        "location": e.location,
        "start_date": e.start_date,
        "end_date": e.end_date,
        "description": e.description,
        "verified": e.verified,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.post("/experiences")
async def create_experience(
    req: ExperienceIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.title.strip() or not req.organization.strip():
        raise HTTPException(status_code=400, detail="Title and organization are both required.")

    profile = get_career_profile_or_404(db, current_user)
    experience = Experience(
        career_profile_id=profile.id,
        title=req.title.strip(),
        organization=req.organization.strip(),
        location=(req.location or "").strip() or None,
        start_date=(req.start_date or "").strip() or None,
        end_date=(req.end_date or "").strip() or None,
        description=(req.description or "").strip() or None,
    )
    db.add(experience)
    db.commit()
    db.refresh(experience)
    return _experience_to_dict(experience)


@router.get("/experiences")
async def list_experiences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    experiences = (
        db.query(Experience)
        .filter_by(career_profile_id=profile.id)
        .order_by(Experience.created_at.desc())
        .all()
    )
    return [_experience_to_dict(e) for e in experiences]


def _get_experience_or_404(db: Session, profile: CareerProfile, experience_id: int) -> Experience:
    experience = (
        db.query(Experience)
        .filter_by(id=experience_id, career_profile_id=profile.id)
        .one_or_none()
    )
    if experience is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    return experience


@router.put("/experiences/{experience_id}")
async def update_experience(
    experience_id: int,
    req: ExperienceIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.title.strip() or not req.organization.strip():
        raise HTTPException(status_code=400, detail="Title and organization are both required.")

    profile = get_career_profile_or_404(db, current_user)
    experience = _get_experience_or_404(db, profile, experience_id)
    experience.title = req.title.strip()
    experience.organization = req.organization.strip()
    experience.location = (req.location or "").strip() or None
    experience.start_date = (req.start_date or "").strip() or None
    experience.end_date = (req.end_date or "").strip() or None
    experience.description = (req.description or "").strip() or None
    db.commit()
    db.refresh(experience)
    return _experience_to_dict(experience)


@router.delete("/experiences/{experience_id}")
async def delete_experience(
    experience_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    experience = _get_experience_or_404(db, profile, experience_id)
    db.delete(experience)
    db.commit()
    return {"deleted": True}


class EducationIn(BaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    graduation_date: str | None = None


def _education_to_dict(e: Education) -> dict:
    return {
        "id": e.id,
        "institution": e.institution,
        "degree": e.degree,
        "field_of_study": e.field_of_study,
        "graduation_date": e.graduation_date,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.post("/education")
async def create_education(
    req: EducationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.institution.strip():
        raise HTTPException(status_code=400, detail="Institution is required.")

    profile = get_career_profile_or_404(db, current_user)
    entry = Education(
        career_profile_id=profile.id,
        institution=req.institution.strip(),
        degree=(req.degree or "").strip() or None,
        field_of_study=(req.field_of_study or "").strip() or None,
        graduation_date=(req.graduation_date or "").strip() or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _education_to_dict(entry)


@router.get("/education")
async def list_education(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entries = (
        db.query(Education)
        .filter_by(career_profile_id=profile.id)
        .order_by(Education.created_at.desc())
        .all()
    )
    return [_education_to_dict(e) for e in entries]


def _get_education_or_404(db: Session, profile: CareerProfile, education_id: int) -> Education:
    entry = (
        db.query(Education)
        .filter_by(id=education_id, career_profile_id=profile.id)
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Education entry not found.")
    return entry


@router.put("/education/{education_id}")
async def update_education(
    education_id: int,
    req: EducationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_education_or_404(db, profile, education_id)
    entry.institution = req.institution.strip()
    entry.degree = (req.degree or "").strip() or None
    entry.field_of_study = (req.field_of_study or "").strip() or None
    entry.graduation_date = (req.graduation_date or "").strip() or None
    db.commit()
    db.refresh(entry)
    return _education_to_dict(entry)


@router.delete("/education/{education_id}")
async def delete_education(
    education_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_education_or_404(db, profile, education_id)
    db.delete(entry)
    db.commit()
    return {"deleted": True}


class CertificationIn(BaseModel):
    name: str
    issuer: str | None = None
    date: str | None = None


def _certification_to_dict(c: Certification) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "issuer": c.issuer,
        "date": c.date,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.post("/certifications")
async def create_certification(
    req: CertificationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Certification name is required.")

    profile = get_career_profile_or_404(db, current_user)
    entry = Certification(
        career_profile_id=profile.id,
        name=req.name.strip(),
        issuer=(req.issuer or "").strip() or None,
        date=(req.date or "").strip() or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _certification_to_dict(entry)


@router.get("/certifications")
async def list_certifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entries = (
        db.query(Certification)
        .filter_by(career_profile_id=profile.id)
        .order_by(Certification.created_at.desc())
        .all()
    )
    return [_certification_to_dict(c) for c in entries]


def _get_certification_or_404(db: Session, profile: CareerProfile, certification_id: int) -> Certification:
    entry = (
        db.query(Certification)
        .filter_by(id=certification_id, career_profile_id=profile.id)
        .one_or_none()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Certification not found.")
    return entry


@router.put("/certifications/{certification_id}")
async def update_certification(
    certification_id: int,
    req: CertificationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_certification_or_404(db, profile, certification_id)
    entry.name = req.name.strip()
    entry.issuer = (req.issuer or "").strip() or None
    entry.date = (req.date or "").strip() or None
    db.commit()
    db.refresh(entry)
    return _certification_to_dict(entry)


@router.delete("/certifications/{certification_id}")
async def delete_certification(
    certification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_certification_or_404(db, profile, certification_id)
    db.delete(entry)
    db.commit()
    return {"deleted": True}


class SkillIn(BaseModel):
    name: str
    source_text: str | None = None
    experience_id: int | None = None


def _skill_to_dict(s: Skill) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "source_text": s.source_text,
        "experience_id": s.experience_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _validate_skill_experience_id(db: Session, profile: CareerProfile, experience_id: int | None) -> int | None:
    """None is always valid (a flat, not-tied-to-a-role skill). A provided
    id must actually belong to this profile - never trust a client-
    supplied id without checking ownership, same rule as everywhere else."""
    if experience_id is None:
        return None
    exists = (
        db.query(Experience)
        .filter_by(id=experience_id, career_profile_id=profile.id)
        .one_or_none()
    )
    if exists is None:
        raise HTTPException(status_code=400, detail="That role no longer exists.")
    return experience_id


@router.post("/skills")
async def create_skill(
    req: SkillIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Skill name is required.")

    profile = get_career_profile_or_404(db, current_user)
    experience_id = _validate_skill_experience_id(db, profile, req.experience_id)
    entry = Skill(
        career_profile_id=profile.id,
        experience_id=experience_id,
        name=req.name.strip(),
        source_text=(req.source_text or "").strip() or None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _skill_to_dict(entry)


@router.get("/skills")
async def list_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entries = (
        db.query(Skill)
        .filter_by(career_profile_id=profile.id)
        .order_by(Skill.created_at.desc())
        .all()
    )
    return [_skill_to_dict(s) for s in entries]


@router.post("/skills-tidy-suggest")
async def suggest_skill_tidy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Read-only: propose short keyword names for saved skills whose names are
    long. Nothing changes until the candidate approves each one in the page,
    which saves through the normal PUT /skills/{id}."""
    profile = get_career_profile_or_404(db, current_user)
    entries = db.query(Skill).filter_by(career_profile_id=profile.id).order_by(Skill.created_at.desc()).all()
    candidates = tidy_candidates([_skill_to_dict(s) for s in entries])
    if not candidates:
        return {"suggestions": []}

    try:
        keywords = await run_in_threadpool(suggest_skill_keywords, candidates)
    except JobMatchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    suggestions = []
    for s in candidates:
        keyword = keywords.get(s["id"])
        if not keyword or keyword.strip().lower() == s["name"].strip().lower():
            continue
        suggestions.append({
            "id": s["id"],
            "name": s["name"],
            "source_text": s["source_text"],
            "experience_id": s["experience_id"],
            "keyword": keyword,
        })
    return {"suggestions": suggestions}


def _get_skill_or_404(db: Session, profile: CareerProfile, skill_id: int) -> Skill:
    entry = db.query(Skill).filter_by(id=skill_id, career_profile_id=profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    return entry


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: int,
    req: SkillIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Skill name is required.")

    profile = get_career_profile_or_404(db, current_user)
    entry = _get_skill_or_404(db, profile, skill_id)
    entry.name = req.name.strip()
    entry.source_text = (req.source_text or "").strip() or None
    entry.experience_id = _validate_skill_experience_id(db, profile, req.experience_id)
    db.commit()
    db.refresh(entry)
    return _skill_to_dict(entry)


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_skill_or_404(db, profile, skill_id)
    db.delete(entry)
    db.commit()
    return {"deleted": True}


# --- Resume-driven ingestion: upload -> extract roles -> discovery
# interview (reuses elevate.py's discover() unchanged) -> candidate
# reviews and saves. The AI calls themselves are stateless, same as every
# existing tool's pattern - but the resulting progress (extracted roles,
# Q&A history, the pending question batch, discovered facts) is persisted
# to ResumeIngestionDraft after each step, so a candidate who leaves and
# comes back later - a different day, a different device - doesn't lose
# their place. This is the product's actual point: an ongoing Career
# Profile, not a one-session tool like the other six.

def _draft_to_dict(d: ResumeIngestionDraft) -> dict:
    return {
        "analysis_summary": d.analysis_summary,
        "roles": d.roles,
        "education": d.education,
        "certifications": d.certifications,
        "categories": d.categories,
        "history": d.history,
        "pending_questions": d.pending_questions,
        "discovered_facts": d.discovered_facts,
        "round_number": d.round_number,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


@router.get("/resume-draft")
async def get_resume_draft(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=profile.id).one_or_none()
    return _draft_to_dict(draft) if draft is not None else None


@router.delete("/resume-draft")
async def discard_resume_draft(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=profile.id).one_or_none()
    if draft is not None:
        db.delete(draft)
        db.commit()
    return {"discarded": True}


@router.post("/resume-start")
async def resume_start(
    resume_file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    content = await resume_file.read()
    is_pdf = (resume_file.filename or "").lower().endswith(".pdf")
    if len(content) > (MAX_PDF_UPLOAD_BYTES if is_pdf else MAX_UPLOAD_BYTES):
        raise HTTPException(status_code=413, detail="File too large (20 MB max for a PDF, 5 MB for other files).")

    try:
        resume_text = extract_text(resume_file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pdf_document_b64 = None
    if not resume_text.strip():
        if not is_pdf:
            raise HTTPException(status_code=400, detail="Could not extract any text from that file.")
        # A PDF made of page images (e.g. a page printed to PDF): the AI reads the pages instead.
        pdf_document_b64 = base64.b64encode(content).decode("ascii")

    try:
        result = await run_in_threadpool(start_resume_review, resume_text, pdf_document_b64)
    except IngestionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    profile = get_career_profile_or_404(db, current_user)
    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=profile.id).one_or_none()
    if draft is None:
        draft = ResumeIngestionDraft(career_profile_id=profile.id)
        db.add(draft)
    draft.analysis_summary = result.get("analysis_summary")
    draft.roles = result.get("roles") or []
    draft.education = result.get("education") or []
    draft.certifications = result.get("certifications") or []
    draft.categories = result.get("categories") or []
    draft.history = []
    draft.pending_questions = result.get("questions") or []
    draft.discovered_facts = []
    draft.round_number = 1
    db.commit()

    return result


class ResumeDiscoverRequest(BaseModel):
    resume_data: dict
    categories: list = []
    history: list = []
    force_finish: bool = False
    round_number: int = 1


@router.post("/resume-discover")
async def resume_discover(
    req: ResumeDiscoverRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    try:
        result = await run_in_threadpool(
            discover, req.resume_data, req.categories, req.history, req.force_finish, req.round_number
        )
    except ElevateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    profile = get_career_profile_or_404(db, current_user)
    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=profile.id).one_or_none()
    if draft is not None:
        draft.history = req.history
        draft.categories = req.categories
        if result.get("stage") == "confirm":
            draft.discovered_facts = result.get("discovered_facts") or []
            draft.pending_questions = []
        else:
            draft.pending_questions = result.get("questions") or []
            draft.round_number = req.round_number + 1
        db.commit()

    return result


class ConfirmedFactAssignment(BaseModel):
    bullet_text: str
    role_index: int  # which entry in roles[] this fact's bullet attaches to


class ResumeSaveRequest(BaseModel):
    roles: list[dict]
    education: list[dict] = []
    certifications: list[dict] = []
    confirmed_facts: list[ConfirmedFactAssignment] = []


@router.post("/resume-save")
async def save_resume_roles(
    req: ResumeSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)

    roles = [dict(r) for r in req.roles]
    for fact in req.confirmed_facts:
        if 0 <= fact.role_index < len(roles):
            bullets = list(roles[fact.role_index].get("bullets") or [])
            bullets.append(fact.bullet_text)
            roles[fact.role_index]["bullets"] = bullets

    # Each role/education/certification may carry an "existing_id" (set by
    # the frontend when it matched this resume-extracted entry against
    # something already in the profile) - when present, merge into that
    # row instead of creating a duplicate. This is what makes uploading a
    # second/updated resume consolidate into the same roles rather than
    # piling up near-duplicates every time.
    created_experiences, updated_experiences = [], []
    for role in roles:
        title = (role.get("title") or "").strip()
        organization = (role.get("organization") or "").strip()
        if not title or not organization:
            continue  # skip incomplete rows rather than fail the whole save
        new_bullets = [b.strip() for b in (role.get("bullets") or []) if b and b.strip()]

        existing_id = role.get("existing_id")
        existing = (
            db.query(Experience).filter_by(id=existing_id, career_profile_id=profile.id).one_or_none()
            if existing_id else None
        )
        if existing is not None:
            existing_lines = [l for l in (existing.description or "").split("\n") if l.strip()]
            merged_lines = existing_lines + [b for b in new_bullets if b not in existing_lines]
            existing.description = "\n".join(merged_lines) or None
            if not existing.location:
                existing.location = (role.get("location") or "").strip() or None
            if not existing.start_date:
                existing.start_date = (role.get("start_date") or "").strip() or None
            if not existing.end_date:
                existing.end_date = (role.get("end_date") or "").strip() or None
            updated_experiences.append(existing)
            continue

        experience = Experience(
            career_profile_id=profile.id,
            title=title,
            organization=organization,
            location=(role.get("location") or "").strip() or None,
            start_date=(role.get("start_date") or "").strip() or None,
            end_date=(role.get("end_date") or "").strip() or None,
            description="\n".join(new_bullets) or None,
            source="resume_upload",
        )
        db.add(experience)
        created_experiences.append(experience)

    created_education, updated_education = [], []
    for entry in req.education:
        institution = (entry.get("institution") or "").strip()
        if not institution:
            continue

        existing_id = entry.get("existing_id")
        existing = (
            db.query(Education).filter_by(id=existing_id, career_profile_id=profile.id).one_or_none()
            if existing_id else None
        )
        if existing is not None:
            if not existing.degree:
                existing.degree = (entry.get("degree") or "").strip() or None
            if not existing.field_of_study:
                existing.field_of_study = (entry.get("field_of_study") or "").strip() or None
            if not existing.graduation_date:
                existing.graduation_date = (entry.get("graduation_date") or "").strip() or None
            updated_education.append(existing)
            continue

        education = Education(
            career_profile_id=profile.id,
            institution=institution,
            degree=(entry.get("degree") or "").strip() or None,
            field_of_study=(entry.get("field_of_study") or "").strip() or None,
            graduation_date=(entry.get("graduation_date") or "").strip() or None,
            source="resume_upload",
        )
        db.add(education)
        created_education.append(education)

    created_certifications, updated_certifications = [], []
    for entry in req.certifications:
        name = (entry.get("name") or "").strip()
        if not name:
            continue

        existing_id = entry.get("existing_id")
        existing = (
            db.query(Certification).filter_by(id=existing_id, career_profile_id=profile.id).one_or_none()
            if existing_id else None
        )
        if existing is not None:
            if not existing.issuer:
                existing.issuer = (entry.get("issuer") or "").strip() or None
            if not existing.date:
                existing.date = (entry.get("date") or "").strip() or None
            updated_certifications.append(existing)
            continue

        certification = Certification(
            career_profile_id=profile.id,
            name=name,
            issuer=(entry.get("issuer") or "").strip() or None,
            date=(entry.get("date") or "").strip() or None,
            source="resume_upload",
        )
        db.add(certification)
        created_certifications.append(certification)

    db.commit()
    all_rows = (
        created_experiences + updated_experiences
        + created_education + updated_education
        + created_certifications + updated_certifications
    )
    for row in all_rows:
        db.refresh(row)

    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=profile.id).one_or_none()
    if draft is not None:
        db.delete(draft)
        db.commit()

    return {
        "experiences": [_experience_to_dict(e) for e in created_experiences + updated_experiences],
        "education": [_education_to_dict(e) for e in created_education + updated_education],
        "certifications": [_certification_to_dict(c) for c in created_certifications + updated_certifications],
        "created_count": len(created_experiences) + len(created_education) + len(created_certifications),
        "updated_count": len(updated_experiences) + len(updated_education) + len(updated_certifications),
    }


# --- Job comparison: paste a job -> compare against the WHOLE Career
# Profile -> gap interview (reuses elevate.py's discover(), same as the
# resume-ingestion flow above) -> build a tailored resume from real
# profile evidence. Stateless - unlike resume ingestion, this doesn't
# persist a resumable draft (no ResumeIngestionDraft writes here), since
# the "Career Profile" itself is already the persistent record; only the
# ingestion-into-profile flow needed cross-session resumability.

MIN_JOB_DESCRIPTION_CHARS = 40
MAX_JOB_DESCRIPTION_CHARS = 15000


def _build_profile_text(db: Session, profile: CareerProfile) -> str:
    experiences = db.query(Experience).filter_by(career_profile_id=profile.id).order_by(Experience.created_at.desc()).all()
    education = db.query(Education).filter_by(career_profile_id=profile.id).all()
    certifications = db.query(Certification).filter_by(career_profile_id=profile.id).all()
    skills = db.query(Skill).filter_by(career_profile_id=profile.id).all()
    skills_by_experience: dict[int, list[Skill]] = {}
    unassigned_skills: list[Skill] = []
    for s in skills:
        if s.experience_id:
            skills_by_experience.setdefault(s.experience_id, []).append(s)
        else:
            unassigned_skills.append(s)

    lines = ["EXPERIENCE:"]
    if experiences:
        for e in experiences:
            dates = " – ".join(d for d in [e.start_date, e.end_date] if d)
            lines.append(f"- {e.title} at {e.organization}" + (f" ({dates})" if dates else ""))
            if e.description:
                for bullet in e.description.split("\n"):
                    if bullet.strip():
                        lines.append(f"  * {bullet.strip()}")
            for s in skills_by_experience.get(e.id, []):
                lines.append(f"  * Skill: {s.name}" + (f" — {s.source_text}" if s.source_text else ""))
    else:
        lines.append("(none recorded yet)")

    lines.append("\nSKILLS (not tied to one specific role):")
    if unassigned_skills:
        for s in unassigned_skills:
            lines.append(f"- {s.name}" + (f" — {s.source_text}" if s.source_text else ""))
    else:
        lines.append("(none recorded yet)")

    lines.append("\nEDUCATION:")
    if education:
        for ed in education:
            parts = [p for p in [ed.degree, ed.field_of_study] if p]
            lines.append(f"- {ed.institution}" + (f": {', '.join(parts)}" if parts else "") + (f" ({ed.graduation_date})" if ed.graduation_date else ""))
    else:
        lines.append("(none recorded yet)")

    lines.append("\nCERTIFICATIONS:")
    if certifications:
        for c in certifications:
            lines.append(f"- {c.name}" + (f" — {c.issuer}" if c.issuer else "") + (f" ({c.date})" if c.date else ""))
    else:
        lines.append("(none recorded yet)")

    return "\n".join(lines)


class JobCompareRequest(BaseModel):
    job_description: str


@router.post("/job-compare")
async def job_compare(
    req: JobCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    job_description = req.job_description.strip()
    if not job_description:
        raise HTTPException(status_code=400, detail="Please paste the job description.")
    if len(job_description) < MIN_JOB_DESCRIPTION_CHARS:
        raise HTTPException(status_code=400, detail="That job description looks too short to work with — please paste the full posting.")
    if len(job_description) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(status_code=400, detail=f"That job description is too long ({len(job_description)} characters, {MAX_JOB_DESCRIPTION_CHARS} max).")

    profile = get_career_profile_or_404(db, current_user)
    profile_text = _build_profile_text(db, profile)

    try:
        result = await run_in_threadpool(compare_to_job, profile_text, job_description)
    except JobMatchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    job_title = (result.get("job_title") or "").strip() or None
    # Computed in code from the requirement lists (None if the model omitted the met list).
    job_fit = compute_job_fit(result["match_report"])
    result["job_fit"] = job_fit
    scan = ScanHistory(
        career_profile_id=profile.id,
        scan_type="job_comparison",
        job_title=job_title,
        summary_text=result["match_report"]["match_rationale"],
        result_data={
            "job_description": job_description,
            "match_report": result["match_report"],
            "job_fit": job_fit,
            "categories": result.get("categories") or [],
            "questions": result.get("questions") or [],
            "job_title": job_title,
            "qa_history": [],
        },
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    return {**result, "scan_history_id": scan.id}


class LinkedInSkillCompareRequest(BaseModel):
    review: dict


@router.post("/linkedin-skill-compare")
async def linkedin_skill_compare(
    req: LinkedInSkillCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Compares the public LinkedIn review's skills with the signed-in person's
    saved skills. Read-only and no AI call; adding anything to the profile goes
    through the normal POST /skills."""
    profile = get_career_profile_or_404(db, current_user)
    names = [s.name for s in db.query(Skill).filter_by(career_profile_id=profile.id).all()]
    roles = [{"title": e.title, "organization": e.organization} for e in db.query(Experience).filter_by(career_profile_id=profile.id).all()]
    return {**compare_skills(req.review, names), "roles_not_in_profile": compare_roles(req.review, roles)}


class JobFitRequest(BaseModel):
    match_report: dict
    confirmed_facts: list[dict] = []


@router.post("/job-fit")
async def job_fit(
    req: JobFitRequest,
    current_user: User = Depends(get_current_user),
):
    """Recalculates the Job Fit after the gap interview: gaps the candidate
    confirmed count as met. Pure code, no AI call and no saved data."""
    return {"job_fit": compute_job_fit(req.match_report, req.confirmed_facts)}


class JobKeywordCheckRequest(BaseModel):
    job_description: str
    confirmed_facts: list[dict] = []


@router.post("/job-keyword-check")
async def job_keyword_check(
    req: JobKeywordCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Optional step before building: which posting terms the profile does not
    literally contain yet. Read-only; the candidate's choices are saved through
    the normal /skills endpoint (or kept as confirmed facts for one resume)."""
    job_description = req.job_description.strip()
    if len(job_description) < MIN_JOB_DESCRIPTION_CHARS:
        raise HTTPException(status_code=400, detail="That job description looks too short to work with — please paste the full posting.")
    if len(job_description) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(status_code=400, detail=f"That job description is too long ({len(job_description)} characters, {MAX_JOB_DESCRIPTION_CHARS} max).")

    profile = get_career_profile_or_404(db, current_user)
    profile_text = _build_profile_text(db, profile)

    try:
        return await run_in_threadpool(keyword_check, profile_text, req.confirmed_facts, job_description)
    except JobMatchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")


class JobDiscoverRequest(BaseModel):
    resume_data: dict
    categories: list = []
    history: list = []
    force_finish: bool = False
    round_number: int = 1


@router.post("/job-discover")
async def job_discover(
    req: JobDiscoverRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        result = await run_in_threadpool(
            discover, req.resume_data, req.categories, req.history, req.force_finish, req.round_number
        )
    except ElevateError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    return result


class JobBuildResumeRequest(BaseModel):
    job_description: str
    confirmed_facts: list[dict] = []
    name: str
    contact: str
    scan_history_id: int | None = None
    qa_history: list[dict] = []


def _validate_scan_history_id(db: Session, profile: CareerProfile, scan_history_id: int | None) -> ScanHistory | None:
    """None is always valid - a resume can be built without a prior
    job-comparison run in this session. A provided id must belong to this
    profile AND be a job_comparison scan - never trust a client-supplied
    id without checking ownership, same rule as _validate_skill_experience_id."""
    if scan_history_id is None:
        return None
    scan = (
        db.query(ScanHistory)
        .filter_by(id=scan_history_id, career_profile_id=profile.id, scan_type="job_comparison")
        .one_or_none()
    )
    if scan is None:
        raise HTTPException(status_code=400, detail="That job comparison no longer exists.")
    return scan


@router.post("/job-build-resume")
async def job_build_resume(
    req: JobBuildResumeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.name.strip() or not req.contact.strip():
        raise HTTPException(status_code=400, detail="Name and contact info are both required.")

    profile = get_career_profile_or_404(db, current_user)
    scan = _validate_scan_history_id(db, profile, req.scan_history_id)
    profile_text = _build_profile_text(db, profile)

    try:
        result = await run_in_threadpool(
            build_checked_resume, profile_text, req.job_description, req.confirmed_facts, req.name.strip(), req.contact.strip()
        )
    except JobMatchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    # role_selection is kept with the saved resume so what was left off stays
    # visible later; skills_style "grouped" makes the .docx print the compact
    # "Label: skill, skill" lines. build_resume_bytes() ignores keys it doesn't use.
    final_resume = {
        **result["resume_data"],
        "skills_style": "grouped",
        "role_selection": result.get("role_selection") or [],
        "term_report": result.get("term_report") or [],
    }
    version = ResumeVersion(
        career_profile_id=profile.id,
        scan_history_id=scan.id if scan else None,
        resume_data=final_resume,
    )
    db.add(version)

    # The gap-interview Q&A itself (every question asked, every answer given)
    # otherwise only ever lived in the frontend's in-memory jobState - save
    # it onto the scan it belongs to now that a resume was actually built
    # from it, so "what was I asked, and how did I answer" survives reload.
    if scan is not None:
        scan.result_data = {**scan.result_data, "qa_history": req.qa_history}
        db.add(scan)

    db.commit()
    db.refresh(version)

    return {**result, "resume_data": final_resume, "resume_version_id": version.id}


class GeneralResumeRequest(BaseModel):
    name: str
    contact: str


@router.post("/build-general-resume")
async def build_general_resume_route(
    req: GeneralResumeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    if not req.name.strip() or not req.contact.strip():
        raise HTTPException(status_code=400, detail="Name and contact info are both required.")

    profile = get_career_profile_or_404(db, current_user)
    profile_text = _build_profile_text(db, profile)

    try:
        result = await run_in_threadpool(build_general_resume, profile_text, req.name.strip(), req.contact.strip())
    except JobMatchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    result["resume_data"] = dedupe_skills(result["resume_data"])
    version = ResumeVersion(
        career_profile_id=profile.id,
        scan_history_id=None,
        resume_data=result["resume_data"],
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    return {**result, "resume_version_id": version.id}


# --- Skill scan: review the WHOLE Career Profile against what's standard
# for the kinds of roles it represents (not tied to a specific job
# posting or a fresh upload). The interview loop reuses the existing
# /job-discover route unchanged - discover() doesn't care what kind of
# gap-finding triggered it, it only ever sees categories/history/
# questions as opaque context.

@router.post("/skill-scan")
async def skill_scan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    profile_text = _build_profile_text(db, profile)

    try:
        result = await run_in_threadpool(start_skill_scan, profile_text)
    except SkillScanError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")

    scan_history_id = None
    questions = result.get("questions") or []
    if not questions:
        # No questions at all means the scan concluded immediately -
        # "nothing new stood out" is itself a real result worth a history
        # entry, not just the save-confirmed path below.
        summary_text = (result.get("analysis_summary") or "").strip() or "Nothing new stood out this time."
        scan = ScanHistory(
            career_profile_id=profile.id,
            scan_type="skill_scan",
            job_title=None,
            summary_text=summary_text,
            result_data={"categories": result.get("categories") or [], "skills": []},
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
        scan_history_id = scan.id

    return {**result, "scan_history_id": scan_history_id}


class SkillScanFactAssignment(BaseModel):
    name: str
    source_text: str = ""
    experience_id: int | None = None  # None = not tied to one specific role - never guessed, always the candidate's own choice


class SkillScanSaveRequest(BaseModel):
    confirmed_facts: list[SkillScanFactAssignment] = []
    analysis_summary: str = ""
    categories: list[str] = []


@router.post("/skill-scan-save")
async def skill_scan_save(
    req: SkillScanSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)

    created = []
    for fact in req.confirmed_facts:
        name = fact.name.strip()
        if not name:
            continue
        experience_id = _validate_skill_experience_id(db, profile, fact.experience_id)
        skill = Skill(
            career_profile_id=profile.id,
            experience_id=experience_id,
            name=name,
            source_text=fact.source_text.strip() or None,
            source="skill_scan",
        )
        db.add(skill)
        created.append(skill)

    db.commit()
    for s in created:
        db.refresh(s)

    scan_history_id = None
    if created:
        summary_text = req.analysis_summary.strip() or f"Found {len(created)} new skill{'s' if len(created) != 1 else ''}."
        scan = ScanHistory(
            career_profile_id=profile.id,
            scan_type="skill_scan",
            job_title=None,
            summary_text=summary_text,
            result_data={"categories": req.categories, "skills": [s.name for s in created]},
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
        scan_history_id = scan.id

    return {"skills": [_skill_to_dict(s) for s in created], "scan_history_id": scan_history_id}


# --- History: read-only logs of past job/skill scans and past generated
# resumes. Ownership-scoped the same way as every other entity in this
# file; no edit-in-place (unlike renderDetailCard's Experience/Education/
# Certification/Skill pattern) since this is a log, not an editable record.

MAX_HISTORY_LIST = 50


def _scan_history_to_dict(s: ScanHistory) -> dict:
    return {
        "id": s.id,
        "scan_type": s.scan_type,
        "job_title": s.job_title,
        "summary_text": s.summary_text,
        "result_data": s.result_data,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/scan-history")
async def list_scan_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entries = (
        db.query(ScanHistory)
        .filter_by(career_profile_id=profile.id)
        .order_by(ScanHistory.created_at.desc())
        .limit(MAX_HISTORY_LIST)
        .all()
    )
    return [_scan_history_to_dict(s) for s in entries]


def _get_scan_history_or_404(db: Session, profile: CareerProfile, scan_history_id: int) -> ScanHistory:
    entry = db.query(ScanHistory).filter_by(id=scan_history_id, career_profile_id=profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return entry


@router.delete("/scan-history/{scan_history_id}")
async def delete_scan_history(
    scan_history_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_scan_history_or_404(db, profile, scan_history_id)
    db.delete(entry)
    db.commit()
    return {"deleted": True}


def _resume_version_to_dict(v: ResumeVersion) -> dict:
    return {
        "id": v.id,
        "scan_history_id": v.scan_history_id,
        "resume_data": v.resume_data,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.get("/resume-versions")
async def list_resume_versions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entries = (
        db.query(ResumeVersion)
        .filter_by(career_profile_id=profile.id)
        .order_by(ResumeVersion.created_at.desc())
        .limit(MAX_HISTORY_LIST)
        .all()
    )
    return [_resume_version_to_dict(v) for v in entries]


def _get_resume_version_or_404(db: Session, profile: CareerProfile, resume_version_id: int) -> ResumeVersion:
    entry = db.query(ResumeVersion).filter_by(id=resume_version_id, career_profile_id=profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Resume not found.")
    return entry


@router.delete("/resume-versions/{resume_version_id}")
async def delete_resume_version(
    resume_version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_resume_version_or_404(db, profile, resume_version_id)
    db.delete(entry)
    db.commit()
    return {"deleted": True}


@router.get("/resume-versions/{resume_version_id}/download")
async def download_resume_version(
    resume_version_id: int,
    ats_mode: bool = False,
    template: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = _get_resume_version_or_404(db, profile, resume_version_id)

    try:
        docx_bytes = build_resume_bytes(entry.resume_data, ats_mode=ats_mode, template=template or _preferred_layout(db, profile))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build resume: {e}")

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=attachment_headers(entry.resume_data.get("name"), "_Resume.docx"),
    )


# --- Application tracker: jobs the candidate says they applied for. The app
# can't know they applied, so every row is entered by them (usually one click
# from the finished-resume screen). Ownership-scoped like everything else;
# linked scan/resume ids are checked against the profile, never trusted.

APPLICATION_STATUSES = ("applied", "no_response", "interview", "rejected", "offer")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ApplicationIn(BaseModel):
    job_title: str
    company: str | None = None
    applied_on: str | None = None
    status: str = "applied"
    notes: str | None = None
    scan_history_id: int | None = None
    resume_version_id: int | None = None


def _application_to_dict(a: Application) -> dict:
    return {
        "id": a.id,
        "job_title": a.job_title,
        "company": a.company,
        "applied_on": a.applied_on,
        "status": a.status,
        "notes": a.notes,
        "scan_history_id": a.scan_history_id,
        "resume_version_id": a.resume_version_id,
        "status_updated_at": a.status_updated_at.isoformat() if a.status_updated_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _validated_application_fields(db: Session, profile: CareerProfile, req: ApplicationIn) -> dict:
    title = req.job_title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Please enter the job title.")
    if req.status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=400, detail="That status isn't one of the options.")
    applied_on = (req.applied_on or "").strip() or date.today().isoformat()
    if not _ISO_DATE.match(applied_on):
        raise HTTPException(status_code=400, detail="Please enter the date applied as a valid date.")
    scan = _validate_scan_history_id(db, profile, req.scan_history_id)
    resume_id = None
    if req.resume_version_id is not None:
        owned = db.query(ResumeVersion).filter_by(id=req.resume_version_id, career_profile_id=profile.id).one_or_none()
        if owned is None:
            raise HTTPException(status_code=400, detail="That resume no longer exists.")
        resume_id = owned.id
    return {
        "job_title": title,
        "company": (req.company or "").strip() or None,
        "applied_on": applied_on,
        "status": req.status,
        "notes": (req.notes or "").strip() or None,
        "scan_history_id": scan.id if scan else None,
        "resume_version_id": resume_id,
    }


@router.post("/applications")
async def create_application(
    req: ApplicationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = Application(career_profile_id=profile.id, **_validated_application_fields(db, profile, req))
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _application_to_dict(entry)


@router.get("/applications")
async def list_applications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entries = (
        db.query(Application)
        .filter_by(career_profile_id=profile.id)
        .order_by(Application.applied_on.desc(), Application.id.desc())
        .all()
    )
    return [_application_to_dict(a) for a in entries]


@router.put("/applications/{application_id}")
async def update_application(
    application_id: int,
    req: ApplicationIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = db.query(Application).filter_by(id=application_id, career_profile_id=profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    fields = _validated_application_fields(db, profile, req)
    if fields["status"] != entry.status:
        entry.status_updated_at = datetime.now(timezone.utc)
    for key, value in fields.items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return _application_to_dict(entry)


@router.delete("/applications/{application_id}")
async def delete_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    entry = db.query(Application).filter_by(id=application_id, career_profile_id=profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    db.delete(entry)
    db.commit()
    return {"deleted": True}


# --- Career Profile basics (migration 0008): the name/contact line that heads a resume.
# Ownership comes only from the token: there is no profile or user id in the path or body.

class ProfileIn(BaseModel):
    display_name: str | None = None
    contact_line: str | None = None


MAX_DISPLAY_NAME_CHARS = 200
MAX_CONTACT_LINE_CHARS = 400


def _profile_basics(profile: CareerProfile) -> dict:
    return {"display_name": profile.display_name, "contact_line": profile.contact_line}


@router.get("/profile")
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "Profile details"):
        return _profile_basics(profile)


@router.put("/profile")
async def update_profile(
    req: ProfileIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    display_name = (req.display_name or "").strip() or None
    contact_line = (req.contact_line or "").strip() or None
    if display_name and len(display_name) > MAX_DISPLAY_NAME_CHARS:
        raise HTTPException(status_code=400, detail=f"Name is too long ({MAX_DISPLAY_NAME_CHARS} characters max).")
    if contact_line and len(contact_line) > MAX_CONTACT_LINE_CHARS:
        raise HTTPException(status_code=400, detail=f"Contact line is too long ({MAX_CONTACT_LINE_CHARS} characters max).")

    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "Profile details"):
        profile.display_name = display_name
        profile.contact_line = contact_line
        db.commit()
        db.refresh(profile)
        return _profile_basics(profile)


# --- Preferred resume layout (migration 0009): pick it once, every download menu starts on it.
# A separate route from /profile on purpose: until the upgrade is applied only this feature waits,
# the name/contact fields keep working. Ownership comes only from the token.

RESUME_LAYOUTS = ("classic", "modern", "traditional")


class ResumeLayoutIn(BaseModel):
    layout: str | None = None


def _preferred_layout(db: Session, profile: CareerProfile) -> str:
    """The saved layout, or Classic when none is saved or the upgrade has not been applied yet.
    Never raises: a download must still work."""
    try:
        value = profile.preferred_resume_layout
    except (OperationalError, ProgrammingError):
        db.rollback()
        return "classic"
    return value if value in RESUME_LAYOUTS else "classic"


@router.get("/resume-layout")
async def get_resume_layout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "The preferred resume layout", "0009"):
        value = profile.preferred_resume_layout
        return {"layout": value if value in RESUME_LAYOUTS else "classic"}


@router.put("/resume-layout")
async def update_resume_layout(
    req: ResumeLayoutIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    layout = (req.layout or "").strip().lower() or "classic"
    if layout not in RESUME_LAYOUTS:
        raise HTTPException(status_code=400, detail="Choose one of: " + ", ".join(RESUME_LAYOUTS) + ".")
    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "The preferred resume layout", "0009"):
        profile.preferred_resume_layout = None if layout == "classic" else layout
        db.commit()
        return {"layout": layout}


# --- Languages (migration 0008) ------------------------------------------------

class LanguageIn(BaseModel):
    name: str
    proficiency: str | None = None


def _language_to_dict(entry: Language) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "proficiency": entry.proficiency,
        "source": entry.source,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _get_language_or_404(db: Session, profile: CareerProfile, language_id: int) -> Language:
    entry = db.query(Language).filter_by(id=language_id, career_profile_id=profile.id).one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Language not found.")
    return entry


@router.get("/languages")
async def list_languages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "Languages"):
        entries = db.query(Language).filter_by(career_profile_id=profile.id).order_by(Language.created_at, Language.id).all()
        return [_language_to_dict(e) for e in entries]


@router.post("/languages")
async def create_language(
    req: LanguageIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Language name is required.")

    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "Languages"):
        entry = Language(
            career_profile_id=profile.id,
            name=name,
            proficiency=(req.proficiency or "").strip() or None,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return _language_to_dict(entry)


@router.put("/languages/{language_id}")
async def update_language(
    language_id: int,
    req: LanguageIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Language name is required.")

    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "Languages"):
        entry = _get_language_or_404(db, profile, language_id)
        entry.name = name
        entry.proficiency = (req.proficiency or "").strip() or None
        db.commit()
        db.refresh(entry)
        return _language_to_dict(entry)


@router.delete("/languages/{language_id}")
async def delete_language(
    language_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    with schema_upgrade_guard(db, "Languages"):
        entry = _get_language_or_404(db, profile, language_id)
        db.delete(entry)
        db.commit()
        return {"deleted": True}


def _collect_export(db: Session, profile: CareerProfile) -> dict:
    """Everything saved for this profile, as plain data. Shared by the data-file backup and the readable copy,
    so the two can never disagree about what is saved."""
    experiences = db.query(Experience).filter_by(career_profile_id=profile.id).order_by(Experience.created_at.desc()).all()
    education = db.query(Education).filter_by(career_profile_id=profile.id).all()
    certifications = db.query(Certification).filter_by(career_profile_id=profile.id).all()
    skills = db.query(Skill).filter_by(career_profile_id=profile.id).all()
    scans = db.query(ScanHistory).filter_by(career_profile_id=profile.id).order_by(ScanHistory.created_at.desc()).all()
    resumes = db.query(ResumeVersion).filter_by(career_profile_id=profile.id).order_by(ResumeVersion.created_at.desc()).all()

    try:
        applications = db.query(Application).filter_by(career_profile_id=profile.id).order_by(Application.applied_on.desc()).all()
    except Exception:
        db.rollback()  # applications table not migrated yet: the backup still works without it
        applications = []

    # Languages need migration 0008. If it has not been applied, say so in the backup itself
    # (and in the log) rather than silently exporting an empty list.
    languages_unavailable = False
    try:
        languages = db.query(Language).filter_by(career_profile_id=profile.id).order_by(Language.created_at, Language.id).all()
    except (OperationalError, ProgrammingError) as e:
        db.rollback()
        if not any(h in str(e).lower() for h in _MISSING_SCHEMA_HINTS):
            raise
        logger.error("Export: languages table missing (run `alembic upgrade head`): %s", e.__class__.__name__)
        languages, languages_unavailable = [], True

    result = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "applications": [_application_to_dict(a) for a in applications],
        "experiences": [_experience_to_dict(e) for e in experiences],
        "education": [_education_to_dict(e) for e in education],
        "certifications": [_certification_to_dict(c) for c in certifications],
        "skills": [_skill_to_dict(s) for s in skills],
        "scan_history": [_scan_history_to_dict(s) for s in scans],
        "languages": [_language_to_dict(l) for l in languages],
        "resume_versions": [_resume_version_to_dict(v) for v in resumes],
    }
    if languages_unavailable:
        result["languages_unavailable"] = "Languages could not be included: the database upgrade (migration 0008) has not been applied."
    return result


@router.get("/export")
async def export_career_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """A full, unfiltered snapshot of everything in the Career Profile -
    a backup the candidate can keep before manually cleaning up their own
    data (merging duplicates, moving misattributed evidence, etc.), not a
    resume and not something generated/polished."""
    profile = get_career_profile_or_404(db, current_user)
    return _collect_export(db, profile)


@router.get("/export/readable")
async def export_career_profile_readable(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """The same snapshot as /export, laid out as a Word document a person can read or print. Only what is saved,
    only the caller's own records (the profile comes from the verified token, like every route here)."""
    profile = get_career_profile_or_404(db, current_user)
    data = _collect_export(db, profile)
    try:
        name, contact = profile.display_name, profile.contact_line
    except (OperationalError, ProgrammingError):
        db.rollback()  # resume-header columns need migration 0008: the copy still works without them
        name = contact = None
    try:
        docx_bytes = build_profile_copy_bytes(data, name, contact)
    except Exception as e:
        logger.error("Readable profile copy failed: %s", e.__class__.__name__)
        raise HTTPException(status_code=500, detail="We couldn't build your readable copy. Please try again.")
    filename = f"My_Career_Profile_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class DeleteAccountIn(BaseModel):
    confirm: str


DELETE_CONFIRM_WORD = "DELETE"


def _delete_rows(db: Session, model, **filters) -> int:
    """Bulk-delete rows. A table that does not exist yet (migrations are applied by hand) counts as 0. It is
    looked for up front, with no savepoint, so the whole deletion stays one plain transaction on any database."""
    if not inspect(db.connection()).has_table(model.__tablename__):
        return 0
    return db.query(model).filter_by(**filters).delete(synchronize_session=False)


@router.post("/account/delete")
async def delete_my_account(
    body: DeleteAccountIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Permanently erase the signed-in person's saved data and their account row here. Whose data this is comes only
    from the verified token (like every route in this file). The person must send the word DELETE so a stray
    request cannot do it. It is a POST (not DELETE) because some proxies drop bodies on DELETE. The browser then
    removes the sign-in account itself; this route never sees or needs the password.

    Order matters: children before parents (skills point at roles, resumes at scans). Everything happens in one
    transaction, so it is all erased or none of it is."""
    if body.confirm.strip() != DELETE_CONFIRM_WORD:
        raise HTTPException(status_code=400, detail=f"To delete everything, send the word {DELETE_CONFIRM_WORD}.")

    counts = {}
    user_id = current_user.id
    profile_id = db.query(CareerProfile.id).filter_by(user_id=user_id).scalar()
    if profile_id is not None:
        for key, model in (
            ("applications", Application), ("resume_versions", ResumeVersion), ("scan_history", ScanHistory),
            ("skills", Skill), ("experiences", Experience), ("education", Education),
            ("certifications", Certification), ("languages", Language), ("drafts", ResumeIngestionDraft),
        ):
            counts[key] = _delete_rows(db, model, career_profile_id=profile_id)
        db.query(CareerProfile).filter_by(id=profile_id).delete(synchronize_session=False)
    db.query(User).filter_by(id=user_id).delete(synchronize_session=False)
    db.commit()
    db.expunge_all()
    logger.info("Account and saved data deleted by their owner (internal id %s): %s", user_id, counts)
    return {"deleted": True, "counts": counts}
