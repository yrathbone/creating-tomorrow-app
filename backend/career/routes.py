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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from career.ingestion import IngestionError, discover, ElevateError, start_resume_review
from db import get_db_session
from extractor import extract_text
from models import CareerProfile, Certification, Education, Experience, ResumeIngestionDraft, User

router = APIRouter()

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB - matches main.py's existing resume-upload limit


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


@router.delete("/experiences/{experience_id}")
async def delete_experience(
    experience_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    profile = get_career_profile_or_404(db, current_user)
    experience = (
        db.query(Experience)
        .filter_by(id=experience_id, career_profile_id=profile.id)
        .one_or_none()
    )
    if experience is None:
        raise HTTPException(status_code=404, detail="Role not found.")
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
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (5 MB max).")

    try:
        resume_text = extract_text(resume_file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from that file.")

    try:
        result = await run_in_threadpool(start_resume_review, resume_text)
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

    created_experiences = []
    for role in roles:
        title = (role.get("title") or "").strip()
        organization = (role.get("organization") or "").strip()
        if not title or not organization:
            continue  # skip incomplete rows rather than fail the whole save
        experience = Experience(
            career_profile_id=profile.id,
            title=title,
            organization=organization,
            location=(role.get("location") or "").strip() or None,
            start_date=(role.get("start_date") or "").strip() or None,
            end_date=(role.get("end_date") or "").strip() or None,
            description="\n".join(b.strip() for b in (role.get("bullets") or []) if b and b.strip()) or None,
            source="resume_upload",
        )
        db.add(experience)
        created_experiences.append(experience)

    created_education = []
    for entry in req.education:
        institution = (entry.get("institution") or "").strip()
        if not institution:
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

    created_certifications = []
    for entry in req.certifications:
        name = (entry.get("name") or "").strip()
        if not name:
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
    for row in created_experiences + created_education + created_certifications:
        db.refresh(row)

    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=profile.id).one_or_none()
    if draft is not None:
        db.delete(draft)
        db.commit()

    return {
        "experiences": [_experience_to_dict(e) for e in created_experiences],
        "education": [_education_to_dict(e) for e in created_education],
        "certifications": [_certification_to_dict(c) for c in created_certifications],
    }
