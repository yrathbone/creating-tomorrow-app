"""Run the job discovery pilot sync by hand: reads each approved employer board once and prints COUNTS ONLY.

Usage (from the backend folder, with the service's own environment):  python job_discovery_run.py

Refuses to run unless CT_JOB_DISCOVERY_ENABLED is on. Nothing is scheduled by this file; a schedule is a separate, approved step.
"""
import json
import os
import sys
from datetime import date

ON_VALUES = ("1", "true", "yes", "on")


def main() -> int:
    if os.environ.get("CT_JOB_DISCOVERY_ENABLED", "").strip().lower() not in ON_VALUES:
        print("STOP: CT_JOB_DISCOVERY_ENABLED is not on. Nothing was fetched.")
        return 2
    from career.job_boards import BoardError, run_sync
    from db import get_db_session

    gen = get_db_session()
    db = next(gen)
    try:
        report = run_sync(db, date.today())
    except BoardError as e:
        print(f"STOP: {e}")
        return 1
    finally:
        db.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
