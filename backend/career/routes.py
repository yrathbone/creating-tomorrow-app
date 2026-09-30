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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from db import get_db_session
from models import CareerProfile, Experience, User

router = APIRouter()


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
