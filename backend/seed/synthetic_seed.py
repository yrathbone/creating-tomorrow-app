"""Synthetic seed data, record-hash manifest and count-only verifier for a FRESH staging database (Gate 2b).

Every value is synthetic: reserved test domains (example.com / example.invalid / example.org), fictional names and
companies, placeholder URLs, and two DOCX files built from fictional resume data (seed/fixtures/). Nothing is copied from
any real database, user, or document.

Design:
  - Every row has a FIXED id and fixed foreign keys, and every timestamp is an explicit fixed value. So every column of
    every row is deterministic, and every column is hashed (the manifest covers the whole row, links included).
  - build_manifest(): one SHA-256 per row over all of its columns. Only hashes are stored.
  - seed_database(session): inserts into an EMPTY database, then resets id sequences past the fixed ids.
  - verify_database(engine): read-only. Returns aggregate counts only: per table, rows not in the manifest, manifest rows
    missing, NULL counts per column; and per foreign key, orphan counts and cross-profile link counts. No row values.

CLI (run from backend/):  python -m seed.synthetic_seed manifest | seed | verify  (seed/verify need --expect-db-name)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from db import Base
import models  # noqa: F401  (registers every table on Base.metadata)

FIXTURE_DIR = Path(__file__).with_name("fixtures")
# Interview drafts are the one VARIABLE timestamp: each seed run stamps them with its own run time. The verifier checks
# that every draft carries the run time of its manifest, within this window. Stale drafts are a retention-test case.
RUN_TIME_WINDOW = timedelta(minutes=5)
# The verifier accepts a seed run only while it is inside the same 30-day window the app uses for interview drafts.
from career.draft_retention import DRAFT_RETENTION  # noqa: E402

# Database names this seed must never write to (the current staging and production databases).
DENY_DB_NAMES = {"creating-tomorrow-staging-db", "creating-tomorrow-db", "creating-tomorrow-staging", "creating-tomorrow"}

# Migration bookkeeping, not application data: reported by name, never hashed.
BOOKKEEPING_TABLES = {"alembic_version"}

# Tables in dependency order (parents before children).
TABLE_ORDER = [
    "users", "career_profiles", "experiences", "skills", "education", "certifications", "languages",
    "scan_histories", "resume_versions", "applications", "opportunities", "opportunity_documents",
    "resume_ingestion_drafts", "job_postings", "job_preferences",
]

UTC = timezone.utc


def ts(day: int, hour: int = 12, month: int = 1, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


def all_columns(table_name: str) -> list[str]:
    return [c.name for c in Base.metadata.tables[table_name].columns]


def _norm(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "len": len(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return value


def row_hash(table_name: str, values: dict) -> str:
    """SHA-256 over EVERY column of the row. A missing column raises KeyError, so nothing is silently NULL."""
    payload = {c: _norm(values[c]) for c in all_columns(table_name)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


JOB_URLS = {
    1001: "https://jobs.example.com/postings/1001",
    1002: "https://jobs.example.com/postings/1002",
    1003: "https://jobs.example.com/postings/1003",
    1004: "https://jobs.example.com/ashby/a-7",
    1005: "https://jobs.example.com/postings/1005",
}
RESUME_A = {"name": "Sam Example", "headline": "Operations Analyst · Reporting and process improvement",
            "contact": "Example City · sam@example.invalid · +1 555 0100",
            "summary": ["Synthetic profile for testing. Reports on weekly metrics and automates monthly reporting."],
            "skills": ["SQL", "Spreadsheet reporting", "Customer communication"],
            "experience": [
                {"title": "Operations Analyst", "subtitle": "Example Co, Example City - 01/22 - 06/24",
                 "bullets": ["Reported on weekly service metrics to three managers.", "Automated a monthly report, saving about 6 hours a month."]},
                {"title": "Support Specialist", "subtitle": "Sample Services, Example City - 03/20 - 12/21",
                 "bullets": ["Resolved about 40 customer tickets a day.", "Wrote two internal help articles."]},
                {"title": "Intern, Data Team", "subtitle": "Example Co, Example City - 06/19 - 08/19",
                 "bullets": ["Cleaned and checked a shared spreadsheet of order records."]},
            ],
            "education": ["Example University, Bachelor of Arts, Information Studies, 2020"],
            "certifications": ["Sample Certificate, 2025"],
            "additional_sections": [{"heading": "Languages", "items": ["English (native)", "Spanish (basic)"]}],
            "lang": "en-US"}
RESUME_B = {"name": "Riley Sample", "headline": "Project coordinator · Field operations",
            "contact": "Sample City · riley@example.invalid",
            "summary": ["Synthetic second profile for two-member isolation tests."],
            "skills": ["Project planning", "Vendor coordination"],
            "experience": [
                {"title": "Project Coordinator", "subtitle": "Sample Services, Sample City - 02/23 - present",
                 "bullets": ["Coordinated four field schedules each month."]},
                {"title": "Field Assistant", "subtitle": "Example Works, Sample City - 05/21 - 01/23",
                 "bullets": ["Logged site visits in a shared tracker."]},
            ],
            "education": ["Sample Technical College, Associate, Operations, 2021"],
            "certifications": [],
            "additional_sections": [],
            "lang": "en-US"}


def synthetic_records(run_at: datetime | None = None) -> dict[str, list[dict]]:
    """Complete synthetic record set. Each record: {"id": fixed id, "fk": {column: fixed parent id or None},
    "v": {column: value}}. Every column of the table must appear once across "id", "fk" and "v" (tested)."""
    docx_a = _fixture("synthetic_resume_sam_example.docx")
    docx_b = _fixture("synthetic_resume_riley_sample.docx")
    rec = lambda i, fk, v: {"id": i, "fk": fk, "v": v}  # noqa: E731
    run_at = run_at or now_utc()  # the one variable timestamp: interview drafts, stamped at this run's time
    return {
        "users": [
            rec(101, {}, {"cognito_sub": "synthetic-sub-0001", "email": "member@example.invalid", "consent_given_at": ts(10, 12), "created_at": ts(10, 12), "deleted_at": None}),
            rec(102, {}, {"cognito_sub": "synthetic-sub-0002", "email": "member.b@example.invalid", "consent_given_at": ts(11, 9), "created_at": ts(11, 9), "deleted_at": None}),
            rec(103, {}, {"cognito_sub": "synthetic-sub-0003", "email": None, "consent_given_at": None, "created_at": ts(12, 8), "deleted_at": None}),
        ],
        "career_profiles": [
            rec(201, {"user_id": 101}, {"created_at": ts(10, 12), "updated_at": ts(20, 10), "display_name": "Sam Example",
                                        "contact_line": "Example City · sam@example.invalid", "preferred_resume_layout": "classic"}),
            rec(202, {"user_id": 102}, {"created_at": ts(11, 9), "updated_at": ts(21, 10), "display_name": "Riley Sample",
                                        "contact_line": "Sample City · riley@example.invalid", "preferred_resume_layout": "modern"}),
            rec(203, {"user_id": 103}, {"created_at": ts(12, 8), "updated_at": ts(12, 8), "display_name": None, "contact_line": None,
                                        "preferred_resume_layout": None}),
        ],
        "experiences": [
            rec(301, {"career_profile_id": 201}, {"title": "Operations Analyst", "organization": "Example Co", "location": "Example City",
                                                  "start_date": "01/22", "end_date": "06/24", "description": "Reported on weekly metrics.\nAutomated a monthly report.",
                                                  "source": "manual", "verified": True, "created_at": ts(10, 13)}),
            rec(302, {"career_profile_id": 201}, {"title": "Support Specialist", "organization": "Sample Services", "location": None,
                                                  "start_date": None, "end_date": None, "description": None, "source": "resume_upload",
                                                  "verified": False, "created_at": ts(10, 14)}),
            rec(303, {"career_profile_id": 201}, {"title": "Intern, Data Team", "organization": "Example Co", "location": "Example City",
                                                  "start_date": "06/19", "end_date": "08/19", "description": "Checked order records.",
                                                  "source": "manual", "verified": True, "created_at": ts(10, 15)}),
            rec(304, {"career_profile_id": 202}, {"title": "Project Coordinator", "organization": "Sample Services", "location": "Sample City",
                                                  "start_date": "02/23", "end_date": None, "description": "Coordinated field schedules.",
                                                  "source": "manual", "verified": True, "created_at": ts(11, 10)}),
        ],
        "skills": [
            rec(401, {"career_profile_id": 201, "experience_id": 301}, {"name": "SQL", "source_text": "Wrote weekly reporting queries.", "source": "manual", "created_at": ts(10, 16)}),
            rec(402, {"career_profile_id": 201, "experience_id": None}, {"name": "Customer communication", "source_text": None, "source": "manual", "created_at": ts(10, 16)}),
            rec(403, {"career_profile_id": 202, "experience_id": 304}, {"name": "Project planning", "source_text": "Planned four field schedules.", "source": "manual", "created_at": ts(11, 11)}),
            rec(404, {"career_profile_id": 202, "experience_id": None}, {"name": "Vendor coordination", "source_text": None, "source": "manual", "created_at": ts(11, 11)}),
        ],
        "education": [
            rec(501, {"career_profile_id": 201}, {"institution": "Example University", "degree": "Bachelor of Arts", "field_of_study": "Information Studies", "graduation_date": "05/20", "source": "manual", "created_at": ts(10, 17)}),
            rec(502, {"career_profile_id": 202}, {"institution": "Sample Technical College", "degree": None, "field_of_study": "Operations", "graduation_date": "05/21", "source": "manual", "created_at": ts(11, 12)}),
        ],
        "certifications": [
            rec(601, {"career_profile_id": 201}, {"name": "Sample Certificate", "issuer": None, "date": "03/25", "source": "manual", "created_at": ts(10, 18)}),
        ],
        "languages": [
            rec(701, {"career_profile_id": 201}, {"name": "English", "proficiency": "Native", "source": "manual", "created_at": ts(10, 18)}),
            rec(702, {"career_profile_id": 201}, {"name": "Spanish", "proficiency": "Basic", "source": "manual", "created_at": ts(10, 19)}),
            rec(703, {"career_profile_id": 202}, {"name": "English", "proficiency": "Professional working proficiency", "source": "manual", "created_at": ts(11, 13)}),
        ],
        "scan_histories": [
            rec(801, {"career_profile_id": 201}, {"scan_type": "job_comparison", "job_title": "Operations Analyst", "summary_text": "Synthetic comparison summary.", "result_data": {"score": 3, "matched": ["SQL"], "missing": []}, "created_at": ts(14, 9)}),
            rec(802, {"career_profile_id": 201}, {"scan_type": "skill_scan", "job_title": None, "summary_text": "Synthetic skill scan.", "result_data": {"skills": ["SQL", "Spreadsheet reporting"]}, "created_at": ts(14, 10)}),
            rec(803, {"career_profile_id": 202}, {"scan_type": "job_comparison", "job_title": "Project Coordinator", "summary_text": "Synthetic comparison summary, second profile.", "result_data": {"score": 2, "matched": ["Project planning"], "missing": ["Budgeting"]}, "created_at": ts(15, 9)}),
            rec(804, {"career_profile_id": 202}, {"scan_type": "skill_scan", "job_title": None, "summary_text": "Synthetic skill scan, second profile.", "result_data": {"skills": ["Project planning"]}, "created_at": ts(15, 10)}),
        ],
        "resume_versions": [
            rec(901, {"career_profile_id": 201, "scan_history_id": 801}, {"resume_data": RESUME_A, "created_at": ts(14, 11)}),
            rec(902, {"career_profile_id": 202, "scan_history_id": 803}, {"resume_data": RESUME_B, "created_at": ts(15, 11)}),
        ],
        "applications": [
            rec(1001, {"career_profile_id": 201, "scan_history_id": 801, "resume_version_id": 901},
                {"job_title": "Operations Analyst", "company": "Example Co", "applied_on": "2026-02-01", "status": "applied", "notes": None,
                 "status_updated_at": ts(16, 9), "created_at": ts(16, 9)}),
            rec(1002, {"career_profile_id": 202, "scan_history_id": 803, "resume_version_id": 902},
                {"job_title": "Project Coordinator", "company": "Sample Services", "applied_on": "2026-02-03", "status": "interview", "notes": "Synthetic note.",
                 "status_updated_at": ts(17, 9), "created_at": ts(17, 9)}),
        ],
        "opportunities": [
            rec(1101, {"career_profile_id": 201, "application_id": None, "approved_resume_version_id": 901},
                {"title": "Operations Analyst", "employer": "Example Co", "job_url": JOB_URLS[1001], "dedupe_key": _sha(JOB_URLS[1001]),
                 "location_text": "Example City", "work_arrangement": "remote", "employment_type": "full_time", "base_min": 60000, "base_max": 70000,
                 "base_period": "year", "pay_note": None, "state": "saved", "dismiss_reason": None, "last_verified_on": "2026-02-02", "notes": None,
                 "approved_resume_hash": _sha("resume 901 approved"), "follow_up_on": None, "created_at": ts(18, 9), "updated_at": ts(18, 9)}),
            rec(1102, {"career_profile_id": 201, "application_id": None, "approved_resume_version_id": None},
                {"title": "Support Specialist", "employer": None, "job_url": JOB_URLS[1002], "dedupe_key": _sha(JOB_URLS[1002]),
                 "location_text": None, "work_arrangement": None, "employment_type": None, "base_min": None, "base_max": None, "base_period": None,
                 "pay_note": None, "state": "dismissed", "dismiss_reason": "Not a fit", "last_verified_on": None, "notes": None,
                 "approved_resume_hash": None, "follow_up_on": None, "created_at": ts(18, 10), "updated_at": ts(18, 10)}),
            rec(1103, {"career_profile_id": 202, "application_id": 1002, "approved_resume_version_id": 902},
                {"title": "Project Coordinator", "employer": "Sample Services", "job_url": JOB_URLS[1003], "dedupe_key": _sha(JOB_URLS[1003]),
                 "location_text": "Sample City", "work_arrangement": "on_site", "employment_type": "full_time", "base_min": 55000, "base_max": 62000,
                 "base_period": "year", "pay_note": "Synthetic pay note.", "state": "applied", "dismiss_reason": None, "last_verified_on": "2026-02-04", "notes": None,
                 "approved_resume_hash": _sha("resume 902 approved"), "follow_up_on": "2026-02-18", "created_at": ts(18, 11), "updated_at": ts(18, 11)}),
        ],
        "opportunity_documents": [
            rec(1201, {"opportunity_id": 1101, "career_profile_id": 201, "resume_version_id": 901},
                {"resume_snapshot": {"name": RESUME_A["name"], "headline": RESUME_A["headline"]}, "layout": "classic", "template": "standard",
                 "ats_mode": False, "renderer": "docx", "content_sha256": hashlib.sha256(docx_a).hexdigest(), "docx": docx_a, "created_at": ts(18, 12)}),
            rec(1202, {"opportunity_id": 1103, "career_profile_id": 202, "resume_version_id": 902},
                {"resume_snapshot": {"name": RESUME_B["name"], "headline": RESUME_B["headline"]}, "layout": "modern", "template": "standard",
                 "ats_mode": False, "renderer": "docx", "content_sha256": hashlib.sha256(docx_b).hexdigest(), "docx": docx_b, "created_at": ts(18, 13)}),
        ],
        "resume_ingestion_drafts": [
            rec(1301, {"career_profile_id": 201},
                {"analysis_summary": "Synthetic draft summary.", "roles": [{"title": "Support Specialist", "organization": "Sample Services"}],
                 "education": [], "certifications": [], "categories": [], "history": [{"q": "Which tools did you use?", "a": "SQL"}],
                 "pending_questions": [{"id": "q1", "text": "Describe one result."}], "discovered_facts": [], "round_number": 2, "updated_at": run_at}),
            rec(1302, {"career_profile_id": 202},
                {"analysis_summary": None, "roles": [], "education": [], "certifications": [], "categories": [], "history": [],
                 "pending_questions": [], "discovered_facts": [], "round_number": 1, "updated_at": run_at}),
        ],
        # Job postings, one row for each status the staging screens display. Status is derived in the comments:
        #   open: closed_on and missing_since are NULL; missing: missing_since set, closed_on NULL;
        #   closed: closed_on set; reopened: seen again after a missing mark (missing_since back to NULL).
        "job_postings": [
            rec(1401, {}, {"source": "greenhouse", "board_token": "example-board", "source_job_id": "1001", "title": "Operations Analyst",
                           "company": "Example Co", "location_text": "Example City", "work_arrangement": "remote", "employment_type": "full_time",
                           "job_url": JOB_URLS[1001], "url_hash": _sha(JOB_URLS[1001]), "first_seen_on": date(2026, 1, 5), "last_seen_on": date(2026, 1, 20),
                           "closed_on": None, "missing_since": None, "created_at": ts(5, 9)}),                 # open
            rec(1402, {}, {"source": "greenhouse", "board_token": "example-board", "source_job_id": "1002", "title": "Support Specialist",
                           "company": "Sample Services", "location_text": None, "work_arrangement": None, "employment_type": None,
                           "job_url": JOB_URLS[1002], "url_hash": _sha(JOB_URLS[1002]), "first_seen_on": date(2026, 1, 6), "last_seen_on": date(2026, 1, 18),
                           "closed_on": None, "missing_since": ts(19, 9), "created_at": ts(6, 9)}),           # missing (pending close)
            rec(1403, {}, {"source": "greenhouse", "board_token": "example-board", "source_job_id": "1003", "title": "Data Coordinator",
                           "company": "Example Co", "location_text": "Example City", "work_arrangement": "on_site", "employment_type": "full_time",
                           "job_url": JOB_URLS[1003], "url_hash": _sha(JOB_URLS[1003]), "first_seen_on": date(2025, 12, 1), "last_seen_on": date(2026, 1, 2),
                           "closed_on": date(2026, 1, 15), "missing_since": ts(6, 9), "created_at": ts(1, 9, month=12, year=2025)}),  # closed
            rec(1404, {}, {"source": "ashby", "board_token": "example-ashby", "source_job_id": "a-7", "title": "Team Lead",
                           "company": "Sample Services", "location_text": "Remote - Example", "work_arrangement": "hybrid", "employment_type": "part_time",
                           "job_url": JOB_URLS[1004], "url_hash": _sha(JOB_URLS[1004]), "first_seen_on": date(2026, 1, 10), "last_seen_on": date(2026, 1, 20),
                           "closed_on": None, "missing_since": None, "created_at": ts(10, 9)}),               # open, second board source
            rec(1405, {}, {"source": "greenhouse", "board_token": "example-board", "source_job_id": "1005", "title": "Analyst",
                           "company": "Example Co", "location_text": "Example City", "work_arrangement": "remote", "employment_type": None,
                           "job_url": JOB_URLS[1005], "url_hash": _sha(JOB_URLS[1005]), "first_seen_on": date(2025, 11, 20), "last_seen_on": date(2026, 1, 20),
                           "closed_on": None, "missing_since": None, "created_at": ts(20, 9, month=11, year=2025)}),  # reopened
        ],
        "job_preferences": [
            rec(1501, {"career_profile_id": 201}, {"target_titles": ["Operations Analyst"], "locations": ["Example City"], "remote_ok": True,
                                                   "onsite_ok": False, "employment_types": ["full_time"], "min_base": 50000, "exclude_words": [],
                                                   "followed_boards": ["greenhouse:example-board"], "updated_at": ts(20, 9)}),
            rec(1502, {"career_profile_id": 202}, {"target_titles": ["Project Coordinator"], "locations": ["Sample City"], "remote_ok": False,
                                                   "onsite_ok": True, "employment_types": ["full_time", "part_time"], "min_base": None, "exclude_words": ["sales"],
                                                   "followed_boards": ["ashby:example-ashby"], "updated_at": ts(21, 9)}),
        ],
    }


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def full_rows(run_at: datetime | None = None) -> dict[str, list[dict]]:
    """Every record as a complete row: id, foreign keys and values, all columns present."""
    out = {}
    for table, recs in synthetic_records(run_at).items():
        out[table] = [{"id": r["id"], **r["fk"], **r["v"]} for r in recs]
    return out


def build_manifest(run_at: datetime | None = None) -> dict:
    """The manifest for one seed run: the run time, and for each table the sorted row hashes, computed from the SAME
    timestamped records that seed_database inserts. Only hashes are stored, never values."""
    run_at = run_at or now_utc()
    rows = full_rows(run_at)
    return {"run_at": run_at.isoformat(), "tables": {t: sorted(row_hash(t, r) for r in rows[t]) for t in TABLE_ORDER}}


def seed_database(session: Session, run_at: datetime | None = None) -> tuple[dict[str, int], dict]:
    """Insert the synthetic rows into an EMPTY database, reset id sequences past the fixed ids, COMMIT, and return
    (rows per table, the manifest for this run)."""
    run_at = run_at or now_utc()
    counts = _seed_rows(session, run_at)
    session.commit()
    return counts, build_manifest(run_at)


def _seed_rows(session: Session, run_at: datetime) -> dict[str, int]:
    """Insert the rows and reset the sequences inside the caller's transaction. Does NOT commit: the caller decides."""
    for table in TABLE_ORDER:
        if session.execute(select(func.count()).select_from(Base.metadata.tables[table])).scalar_one():
            raise RuntimeError(f"refusing to seed: table {table} is not empty")
    model_by_table = {m.class_.__tablename__: m.class_ for m in Base.registry.mappers}
    rows_by_table = full_rows(run_at)
    counts: dict[str, int] = {}
    for table in TABLE_ORDER:
        model = model_by_table[table]
        for row in rows_by_table[table]:
            session.add(model(**row))
        session.flush()
        counts[table] = len(rows_by_table[table])
    for table in TABLE_ORDER:
        session.execute(text(
            f'SELECT setval(pg_get_serial_sequence(\'{table}\', \'id\'), '
            f'(SELECT COALESCE(MAX(id), 1) FROM "{table}"), (SELECT MAX(id) IS NOT NULL FROM "{table}"))'
        ))
    return counts


def _table_names(conn) -> list[str]:
    return [r[0] for r in conn.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"))]


def _relationship_counts(conn, present: set[str]) -> dict[str, dict]:
    """For every foreign key: rows whose parent is missing (orphans), and rows whose parent belongs to another profile."""
    out: dict[str, dict] = {}
    for table in TABLE_ORDER:
        if table not in present:
            continue
        for fk in Base.metadata.tables[table].foreign_keys:
            col, parent, pcol = fk.parent.name, fk.column.table.name, fk.column.name
            if parent not in present:
                continue
            orphans = conn.execute(text(
                f'SELECT count(*) FROM "{table}" c WHERE c."{col}" IS NOT NULL AND NOT EXISTS '
                f'(SELECT 1 FROM "{parent}" p WHERE p."{pcol}" = c."{col}")')).scalar_one()
            cross = None
            child_cols = set(all_columns(table))
            parent_cols = set(all_columns(parent))
            if "career_profile_id" in child_cols and "career_profile_id" in parent_cols:
                cross = conn.execute(text(
                    f'SELECT count(*) FROM "{table}" c JOIN "{parent}" p ON p."{pcol}" = c."{col}" '
                    f'WHERE c.career_profile_id IS DISTINCT FROM p.career_profile_id')).scalar_one()
            out[f"{table}.{col}->{parent}.{pcol}"] = {"orphans": orphans, "cross_profile": cross}
    return out


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def verify_database(engine, manifest: dict) -> dict:
    """Read-only comparison with one run's manifest, relationship checks, and two explicit time checks:
      - each draft's updated_at must carry that run's time (within RUN_TIME_WINDOW);
      - the manifest's run time must lie inside the draft-retention window (DRAFT_RETENTION, measured from now).
    A seed run older than the window is rejected even when every hash matches. Returns counts only: never row values."""
    if manifest is None:
        raise TypeError("an explicit manifest from one seed run is required")
    expected = manifest["tables"]
    run_at = datetime.fromisoformat(manifest["run_at"])
    age = _aware(now_utc()) - _aware(run_at)
    result: dict = {"tables": {}, "relationships": {}}
    conn = engine.connect().execution_options(postgresql_readonly=True)
    try:
        present = set(_table_names(conn))
        result["unexpected_tables"] = sorted(present - set(expected) - BOOKKEEPING_TABLES)
        result["missing_tables"] = sorted(set(expected) - present)
        for table in TABLE_ORDER:
            if table not in present:
                continue
            cols = all_columns(table)
            rows = conn.execute(text(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"')).mappings().all()
            db_hashes = Counter(row_hash(table, dict(r)) for r in rows)
            exp = Counter(expected.get(table, []))
            matched = sum((db_hashes & exp).values())
            result["tables"][table] = {
                "rows": len(rows),
                "expected_rows": sum(exp.values()),
                "rows_not_in_manifest": len(rows) - matched,
                "manifest_rows_missing": sum(exp.values()) - matched,
                "null_counts": {c: sum(1 for r in rows if r[c] is None) for c in cols},
            }
        result["relationships"] = _relationship_counts(conn, present)
        draft_times = []
        if "resume_ingestion_drafts" in present:
            draft_times = [_aware(v) for v in conn.execute(text('SELECT updated_at FROM "resume_ingestion_drafts"')).scalars()]
        result["draft_timestamps_in_run_window"] = (
            len(draft_times) == len(expected.get("resume_ingestion_drafts", []))
            and all(abs(v - _aware(run_at)) <= RUN_TIME_WINDOW for v in draft_times)
        )
    finally:
        conn.close()
    # A run is accepted only inside the draft-retention window, with a small allowance for clock skew in the future.
    result["manifest_within_retention_window"] = -RUN_TIME_WINDOW <= age <= DRAFT_RETENTION
    rel_ok = all(v["orphans"] == 0 and (v["cross_profile"] in (None, 0)) for v in result["relationships"].values())
    result["pass"] = (
        not result["unexpected_tables"] and not result["missing_tables"] and rel_ok
        and result["draft_timestamps_in_run_window"] and result["manifest_within_retention_window"]
        and all(t["rows_not_in_manifest"] == 0 and t["manifest_rows_missing"] == 0 for t in result["tables"].values())
    )
    return result


def _url_for(env_name: str, expect_db_name: str) -> str:
    raw = os.environ.get(env_name, "")
    if not raw:
        raise SystemExit(f"{env_name} is not set")
    parts = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    name = (parts.path or "/").lstrip("/")
    if name != expect_db_name:
        raise SystemExit("refusing: database name does not match --expect-db-name")
    if name in DENY_DB_NAMES:
        raise SystemExit("refusing: database name is on the deny list")
    return raw if raw.startswith("postgresql+psycopg://") else raw.replace("postgresql://", "postgresql+psycopg://", 1)


def _prepare_manifest_file(out: Path, manifest: dict) -> Path:
    """Write the manifest to a temporary file in the target folder and return its path. Raises BEFORE any row is inserted
    if the folder is missing, the file already exists, or the write fails. The caller publishes it with os.replace."""
    if not out.parent.is_dir():
        raise FileNotFoundError("manifest folder does not exist")
    if out.exists():
        raise FileExistsError("refusing to overwrite an existing manifest")
    fd, tmp_name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=str(out.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return Path(tmp_name)


def _unknown_commit(url_env: str, out: Path, manifest: dict, error: str, verify_error: str | None = None) -> int:
    """The database outcome could not be established. The manifest is KEPT, and the operator gets the command to verify later."""
    print(json.dumps({
        "error": error,
        "status": "commit_outcome_unknown",
        "committed": None,
        "manifest_kept": str(out),
        "run_at": manifest["run_at"],
        "verification_error": verify_error,
        "verify_later": f"python -m seed.synthetic_seed verify --url-env {url_env} --expect-db-name ct_seed_disposable --manifest \"{out}\"",
    }, sort_keys=True))
    return 3


def _resolve_uncertain_commit(url: str, url_env: str, out: Path, manifest: dict, error: str) -> int:
    """The COMMIT raised after the manifest was published. The commit may still be in progress, or may have happened
    without its acknowledgement, so an exception does not prove rollback, and an empty read does not either (a fresh
    connection can read before a pending commit becomes visible). The manifest is therefore KEPT unless a fresh
    read-only verification POSITIVELY passes against it:
      - the verifier passes: the commit is verified, the manifest is kept, exit 0;
      - the verifier fails (including empty tables), or the fresh connection cannot be made or used: the outcome is
        unknown, the manifest is kept, the verify command is printed for later, exit 3.
    Only failures before the COMMIT call (see _seed_command) remove the manifest."""
    try:
        fresh = create_engine(url, pool_pre_ping=True)
    except Exception as exc:
        return _unknown_commit(url_env, out, manifest, error, type(exc).__name__)
    try:
        result = verify_database(fresh, manifest)
    except Exception as exc:
        return _unknown_commit(url_env, out, manifest, error, type(exc).__name__)
    finally:
        fresh.dispose()
    if result["pass"]:
        print(json.dumps({"error": error, "status": "commit_verified_by_fresh_connection", "committed": True,
                          "run_at": manifest["run_at"], "manifest_kept": str(out)}, sort_keys=True))
        return 0
    return _unknown_commit(url_env, out, manifest, error)

def _seed_command(args) -> int:
    """Seed an empty database and publish this run's manifest. Order:
      1. validate the database target and create the engine (no side effects);
      2. write the manifest to a temporary file beside the output path (no rows yet);
      3. in ONE transaction: insert the rows, publish the manifest with os.replace, then COMMIT.
    Failures before the publish: the transaction is rolled back and the temporary file is removed (exit 2).
    A COMMIT that raises after the publish is an UNCERTAIN outcome: the manifest is kept unless a fresh read-only
    verification positively passes (see _resolve_uncertain_commit). Exit codes: 0 committed and verified; 2 failed before
    the publish (rolled back, temporary file removed); 3 outcome unknown, manifest kept."""
    out = Path(args.manifest_out)
    engine = None
    tmp = None
    published = False
    url = None
    manifest = None
    try:
        url = _url_for(args.url_env, args.expect_db_name)
        engine = create_engine(url, pool_pre_ping=True)
        run_at = now_utc()
        manifest = build_manifest(run_at)
        tmp = _prepare_manifest_file(out, manifest)
        with Session(engine) as session:
            counts = _seed_rows(session, run_at)
            if build_manifest(run_at) != manifest:
                raise RuntimeError("the seeded records do not match the prepared manifest")
            os.replace(tmp, out)
            published = True
            session.commit()
        print(json.dumps({"seeded_rows_per_table": counts, "run_at": manifest["run_at"], "status": "committed"}, sort_keys=True))
        return 0
    except (Exception, SystemExit) as exc:  # report the class only: messages may contain data
        error = type(exc).__name__
        if not published:
            if tmp is not None:
                Path(tmp).unlink(missing_ok=True)
            print(json.dumps({"error": error, "status": "rolled_back_before_publish", "committed": False}, sort_keys=True))
            return 2
        return _resolve_uncertain_commit(url, args.url_env, out, manifest, error)
    finally:
        if engine is not None:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic seed for a fresh database (Gate 2b).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifest", help="print the record-hash manifest (no database used)")
    p_seed = sub.add_parser("seed", help="seed an EMPTY database; writes this run's manifest to --manifest-out")
    p_seed.add_argument("--url-env", required=True, help="environment variable holding the connection string")
    p_seed.add_argument("--expect-db-name", required=True)
    p_seed.add_argument("--manifest-out", required=True, help="where to write this run's manifest (hashes only; keep it local)")
    p_ver = sub.add_parser("verify", help="read-only verification against one run's manifest (counts only)")
    p_ver.add_argument("--url-env", required=True, help="environment variable holding the connection string")
    p_ver.add_argument("--expect-db-name", required=True)
    p_ver.add_argument("--manifest", required=True, help="the manifest written by the seed run")
    args = parser.parse_args(argv)
    if args.cmd == "manifest":
        print(json.dumps(build_manifest(), indent=1, sort_keys=True))
        return 0
    if args.cmd == "seed":
        return _seed_command(args)
    engine = create_engine(_url_for(args.url_env, args.expect_db_name), pool_pre_ping=True)
    try:
        result = verify_database(engine, json.loads(Path(args.manifest).read_text(encoding="utf-8")))
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0 if result["pass"] else 1
    except Exception as exc:  # report the class only: messages may contain data
        print(json.dumps({"error": type(exc).__name__}))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
