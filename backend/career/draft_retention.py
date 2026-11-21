"""Interview-draft retention: a resume-interview draft is deleted after 30 days without an update.

"Without an update" uses the draft's existing updated_at column, which the database sets on every change (see
models.ResumeIngestionDraft). Reading a draft never changes updated_at, so viewing it does not reset the clock.

Two protections, both deleting permanently:
  1. On read: a draft older than the window is treated as gone and deleted before anything else happens (live_draft).
  2. Daily sweep: career/draft_sweep.py (run by a Render Cron service) deletes every stale draft, including ones nobody opens.

Only resume_ingestion_drafts rows are affected. Saved resumes (resume_versions), job-comparison and skill-scan history
(scan_history), applications and the Career Profile are never touched here.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import ResumeIngestionDraft

DRAFT_RETENTION = timedelta(days=30)


def draft_cutoff(now: datetime | None = None) -> datetime:
    """Drafts last updated before this instant are stale."""
    return (now or datetime.now(timezone.utc)) - DRAFT_RETENTION


def is_stale(draft: ResumeIngestionDraft, now: datetime | None = None) -> bool:
    if draft.updated_at is None:
        # The column has a server default and is never null in practice; if it ever were, keep the draft rather than guess.
        return False
    updated = draft.updated_at if draft.updated_at.tzinfo else draft.updated_at.replace(tzinfo=timezone.utc)
    return updated < draft_cutoff(now)


def live_draft(db: Session, career_profile_id: int, now: datetime | None = None) -> ResumeIngestionDraft | None:
    """The profile's draft if it is still within the window. A stale draft is deleted and reported as absent."""
    draft = db.query(ResumeIngestionDraft).filter_by(career_profile_id=career_profile_id).one_or_none()
    if draft is None:
        return None
    if is_stale(draft, now):
        db.delete(draft)
        db.commit()
        return None
    return draft


def sweep_stale_drafts(db: Session, now: datetime | None = None) -> int:
    """Permanently deletes every draft with no update in the window. Returns how many rows were deleted (a count, nothing else)."""
    deleted = (
        db.query(ResumeIngestionDraft)
        .filter(ResumeIngestionDraft.updated_at < draft_cutoff(now))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
