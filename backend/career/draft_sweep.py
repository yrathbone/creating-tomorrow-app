"""Daily sweep for interview drafts (run by the Render Cron service creating-tomorrow-draft-sweep).

Deletes every resume_ingestion_drafts row with no update for 30 days (career/draft_retention.py). Prints a count only.
Draft content is never read or printed here.

Run from backend/:  python -m career.draft_sweep
Needs DATABASE_URL in the environment. FOR REVIEW ONLY: not scheduled or deployed.
"""
import sys

from career.draft_retention import sweep_stale_drafts
from db import get_session


def main() -> int:
    session = get_session()
    try:
        deleted = sweep_stale_drafts(session)
    finally:
        session.close()
    print(f"interview drafts deleted: {deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
