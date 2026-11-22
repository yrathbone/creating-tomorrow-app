"""Interview-draft retention (Jo direction, 2026-11-22): a resume-interview draft expires DRAFT_RETENTION after its last
change, and the member can discard it sooner (DELETE /api/career/resume-draft, unchanged).

"Last activity" is ResumeIngestionDraft.updated_at, which the database sets on every write to the draft. Reads do not
extend it.

Two enforcement points, both server-side and both deleting the row:
  - live_draft(): every read or write path that loads the draft uses it, so an expired draft is never returned.
  - sweep_stale_drafts(): removes every expired draft in one pass. Nothing calls it on a schedule yet, so until a
    scheduler runs it, a draft that is never read again is kept in the database. Do not describe the 30-day rule as
    active for unread drafts until that scheduler is wired and reviewed.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import ResumeIngestionDraft

DRAFT_RETENTION = timedelta(days=30)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _expired(draft: ResumeIngestionDraft, now: datetime) -> bool:
    last = _utc(draft.updated_at)
    # A draft with no recorded last activity is treated as expired: nothing proves it is recent.
    return last is None or now - last >= DRAFT_RETENTION


def live_draft(db: Session, career_profile_id: int, now: datetime | None = None) -> ResumeIngestionDraft | None:
    """The profile's draft if it is still within retention. An expired draft is deleted here and None is returned."""
    now = now or datetime.now(timezone.utc)
    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=career_profile_id).one_or_none()
    if draft is None:
        return None
    if _expired(draft, now):
        db.delete(draft)
        db.commit()
        return None
    return draft


def sweep_stale_drafts(db: Session, now: datetime | None = None) -> int:
    """Delete every expired draft. Returns how many were removed. Compares in Python so SQLite and PostgreSQL agree."""
    now = now or datetime.now(timezone.utc)
    removed = 0
    for draft in db.query(ResumeIngestionDraft).all():
        if _expired(draft, now):
            db.delete(draft)
            removed += 1
    if removed:
        db.commit()
    return removed
