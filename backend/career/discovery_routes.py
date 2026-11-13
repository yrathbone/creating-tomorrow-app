"""Job discovery pilot routes: a member's preferences, the boards they follow, and their matches.

Feature switch: CT_JOB_DISCOVERY_ENABLED (default off). Allowlist: CT_JOB_DISCOVERY_ALLOWED_SUBS (default: nobody). When the
switch is off, or the account is not on the allowlist, every route answers 404, the same as the rest of the career area.

Reviewing a match does not add a new route: the frontend creates a saved link with the existing POST /api/career/opportunities
and then runs the existing compare flow (C-52). Nothing here calls an AI service or a job board.
"""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from career import discovery
from career.job_boards import BoardError, board_key, load_registry
from career.routes import get_career_profile_or_404
from db import get_db_session
from models import Experience, JobPosting, JobPreference, Opportunity, Skill, User

FOLLOW_LIMIT = 10
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "temporary", "internship", "other")
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


def require_discovery_enabled() -> None:
    if os.environ.get("CT_JOB_DISCOVERY_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=404, detail="Not found.")


def discovery_allowed_subs() -> set:
    raw = os.environ.get("CT_JOB_DISCOVERY_ALLOWED_SUBS", "")
    return {v.strip() for v in raw.split(",") if v.strip()}


def require_discovery_member(current_user: User = Depends(get_current_user)) -> None:
    if not current_user.cognito_sub or current_user.cognito_sub not in discovery_allowed_subs():
        raise HTTPException(status_code=404, detail="Not found.")


def follow_limit() -> int:
    """Fixed at 10 for the pilot, in code. Not configurable at runtime: raising it is a code change and a review."""
    return FOLLOW_LIMIT


router = APIRouter(dependencies=[Depends(require_discovery_enabled), Depends(require_discovery_member)])


class PreferencesIn(BaseModel):
    target_titles: list[ShortText] = Field(default_factory=list, max_length=10)
    locations: list[ShortText] = Field(default_factory=list, max_length=10)
    remote_ok: bool = True
    onsite_ok: bool = True
    employment_types: list[str] = Field(default_factory=list, max_length=6)
    min_base: int | None = Field(default=None, ge=0, le=10_000_000)
    exclude_words: list[ShortText] = Field(default_factory=list, max_length=20)
    followed_boards: list[str] = Field(default_factory=list, max_length=50)


def _approved_keys() -> dict:
    try:
        return {board_key(b): b["name"] for b in load_registry()}
    except (BoardError, OSError, ValueError):
        raise HTTPException(status_code=503, detail="The list of job boards is not available right now.")


def _prefs_dict(row: JobPreference | None) -> dict:
    if row is None:
        return {"target_titles": [], "locations": [], "remote_ok": True, "onsite_ok": True, "employment_types": [],
                "min_base": None, "exclude_words": [], "followed_boards": []}
    return {"target_titles": list(row.target_titles or []), "locations": list(row.locations or []), "remote_ok": row.remote_ok,
            "onsite_ok": row.onsite_ok, "employment_types": list(row.employment_types or []), "min_base": row.min_base,
            "exclude_words": list(row.exclude_words or []), "followed_boards": list(row.followed_boards or [])}


def _preferences_response(prefs: dict, approved: dict) -> dict:
    return {
        **prefs,
        "follow_limit": follow_limit(),
        "available_boards": [{"key": key, "name": name} for key, name in approved.items()],
        "pilot_note": "Creating Tomorrow does not endorse employers. Postings are listed for you to review; the app never applies for you.",
    }


@router.get("/job-preferences")
def get_job_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    row = db.query(JobPreference).filter_by(career_profile_id=profile.id).one_or_none()
    return _preferences_response(_prefs_dict(row), _approved_keys())


@router.put("/job-preferences")
def put_job_preferences(req: PreferencesIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    approved = _approved_keys()
    boards = list(dict.fromkeys(req.followed_boards))
    unknown = [b for b in boards if b not in approved]
    if unknown:
        raise HTTPException(status_code=400, detail="One or more boards are not on the approved list.")
    if len(boards) > follow_limit():
        raise HTTPException(status_code=400, detail=f"You can follow up to {follow_limit()} job boards.")
    bad_types = [t for t in req.employment_types if t not in EMPLOYMENT_TYPES]
    if bad_types:
        raise HTTPException(status_code=400, detail="One or more employment types are not recognised.")

    row = db.query(JobPreference).filter_by(career_profile_id=profile.id).one_or_none()
    if row is None:
        row = JobPreference(career_profile_id=profile.id)
        db.add(row)
    row.target_titles = list(dict.fromkeys(req.target_titles))
    row.locations = list(dict.fromkeys(req.locations))
    row.remote_ok, row.onsite_ok = req.remote_ok, req.onsite_ok
    row.employment_types = list(dict.fromkeys(req.employment_types))
    row.min_base = req.min_base
    row.exclude_words = list(dict.fromkeys(req.exclude_words))
    row.followed_boards = boards
    db.commit()
    return _preferences_response(_prefs_dict(row), approved)


def _followed_pairs(boards: list[str]) -> list[tuple[str, str]]:
    pairs = []
    for key in boards:
        source, _, token = key.partition(":")
        if source and token:
            pairs.append((source, token))
    return pairs


@router.get("/job-matches")
def get_job_matches(current_user: User = Depends(get_current_user), db: Session = Depends(get_db_session)):
    profile = get_career_profile_or_404(db, current_user)
    row = db.query(JobPreference).filter_by(career_profile_id=profile.id).one_or_none()
    prefs = _prefs_dict(row)
    pairs = _followed_pairs(prefs["followed_boards"])
    if not pairs:
        return {"matches": [], "message": "Follow at least one job board to see matches."}

    postings = db.query(JobPosting).filter(
        JobPosting.closed_on.is_(None),
        or_(*[and_(JobPosting.source == s, JobPosting.board_token == t) for s, t in pairs]),
    ).all()
    terms = discovery.profile_terms(
        [e.title for e in db.query(Experience).filter_by(career_profile_id=profile.id).all()],
        [s.name for s in db.query(Skill).filter_by(career_profile_id=profile.id).all()],
    )
    saved_keys = {o.dedupe_key for o in db.query(Opportunity).filter_by(career_profile_id=profile.id).all()}

    ranked = discovery.rank(postings, prefs, terms)
    return {
        "matches": [
            {
                "id": posting.id,
                "title": posting.title,
                "company": posting.company,
                "location_text": posting.location_text,
                "work_arrangement": posting.work_arrangement,
                "employment_type": posting.employment_type,
                "first_seen_on": posting.first_seen_on.isoformat(),
                "job_url": posting.job_url,
                "reasons": result["reasons"],
                "already_saved": posting.url_hash in saved_keys,
            }
            for posting, result in ranked
        ],
        "message": "" if ranked else "No open postings match your preferences yet.",
    }
