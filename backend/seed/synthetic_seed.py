"""Synthetic seed data and record-hash manifest for a FRESH staging database (Gate 2b).

Every value here is synthetic: reserved test domains (example.com / example.invalid), fictional names and
companies, and placeholder URLs. Nothing is copied from any real database or user.

What it provides:
  - synthetic_records(): one complete record set per application table (business columns, with
    foreign keys written as logical keys), including deliberate NULLs.
  - build_manifest(): one SHA-256 per record over its business columns (ids, foreign keys and
    server timestamps are excluded). Only hashes are stored, never values.
  - seed_database(session): inserts the records into an EMPTY database.
  - verify_database(engine, manifest): read-only, returns aggregate counts only (no row values).

Run from backend/ (see the CLI at the bottom). The CLI refuses unless the target database name is
given explicitly and is not on the deny list.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from db import Base
import models  # noqa: F401  (registers every table on Base.metadata)

MANIFEST_PATH = Path(__file__).with_name("synthetic_manifest.json")

# Bookkeeping columns that the database fills in: excluded from the hash.
SERVER_COLUMNS = {"id", "created_at", "updated_at", "status_updated_at", "deleted_at"}

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


def business_columns(table_name: str) -> list[str]:
    """Columns that carry content: everything except ids, server timestamps and foreign keys."""
    table = Base.metadata.tables[table_name]
    fk_cols = {fk.parent.name for fk in table.foreign_keys}
    return [c.name for c in table.columns if c.name not in SERVER_COLUMNS and c.name not in fk_cols]


def _fk_columns(table_name: str) -> dict[str, str]:
    """Foreign-key column -> referenced table name."""
    table = Base.metadata.tables[table_name]
    return {fk.parent.name: fk.column.table.name for fk in table.foreign_keys}


def _norm(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "len": len(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return value


def row_hash(table_name: str, values: dict) -> str:
    """SHA-256 over the business columns of one row. A missing column raises KeyError (coverage check)."""
    payload = {c: _norm(values[c]) for c in business_columns(table_name)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sha(text_value: str) -> str:
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


UTC = timezone.utc
JOB_URL_1 = "https://jobs.example.com/postings/1001"
JOB_URL_2 = "https://jobs.example.com/postings/1002"
DOCX_FIXTURE = b"synthetic-docx-fixture-v1"


def synthetic_records() -> dict[str, list[dict]]:
    """Complete synthetic record set. Each record: {"key": logical name, "fk": {column: logical key}, "v": {column: value}}.
    Foreign keys are logical keys resolved at seed time. Every business column is given an explicit value (NULL where
    the model allows it), so the hash covers the full row."""
    return {
        "users": [
            {"key": "u_a", "fk": {}, "v": {"cognito_sub": "synthetic-sub-0001", "email": "member@example.invalid",
                                         "consent_given_at": datetime(2026, 1, 10, 12, 0, tzinfo=UTC)}},
            {"key": "u_b", "fk": {}, "v": {"cognito_sub": "synthetic-sub-0002", "email": None, "consent_given_at": None}},
        ],
        "career_profiles": [
            {"key": "p_a", "fk": {"user_id": "u_a"}, "v": {"display_name": "Sam Example", "contact_line": "Example City · sam@example.invalid",
                                                          "preferred_resume_layout": "classic"}},
            {"key": "p_b", "fk": {"user_id": "u_b"}, "v": {"display_name": None, "contact_line": None, "preferred_resume_layout": None}},
        ],
        "experiences": [
            {"key": "e_1", "fk": {"career_profile_id": "p_a"}, "v": {"title": "Operations Analyst", "organization": "Example Co",
                                                                   "location": "Example City", "start_date": "01/22", "end_date": "06/24",
                                                                   "description": "Reported on weekly metrics.\nAutomated a monthly report.",
                                                                   "source": "manual", "verified": True}},
            {"key": "e_2", "fk": {"career_profile_id": "p_a"}, "v": {"title": "Support Specialist", "organization": "Sample Services",
                                                                   "location": None, "start_date": None, "end_date": None,
                                                                   "description": None, "source": "resume_upload", "verified": False}},
        ],
        "skills": [
            {"key": "s_1", "fk": {"career_profile_id": "p_a", "experience_id": "e_1"}, "v": {"name": "SQL",
                                                                                              "source_text": "Wrote weekly reporting queries.",
                                                                                              "source": "manual"}},
            {"key": "s_2", "fk": {"career_profile_id": "p_a", "experience_id": None}, "v": {"name": "Customer communication",
                                                                                            "source_text": None, "source": "manual"}},
        ],
        "education": [
            {"key": "ed_1", "fk": {"career_profile_id": "p_a"}, "v": {"institution": "Example University", "degree": "Bachelor of Arts",
                                                                     "field_of_study": None, "graduation_date": "05/20", "source": "manual"}},
        ],
        "certifications": [
            {"key": "c_1", "fk": {"career_profile_id": "p_a"}, "v": {"name": "Sample Certificate", "issuer": None, "date": "03/25",
                                                                     "source": "manual"}},
        ],
        "languages": [
            {"key": "l_1", "fk": {"career_profile_id": "p_a"}, "v": {"name": "English", "proficiency": "Native", "source": "manual"}},
        ],
        "scan_histories": [
            {"key": "sh_1", "fk": {"career_profile_id": "p_a"}, "v": {"scan_type": "job_comparison", "job_title": "Operations Analyst",
                                                                     "summary_text": "Synthetic comparison summary.",
                                                                     "result_data": {"score": 3, "matched": ["SQL"], "missing": []}}},
            {"key": "sh_2", "fk": {"career_profile_id": "p_a"}, "v": {"scan_type": "skill_scan", "job_title": None,
                                                                     "summary_text": "Synthetic skill scan.",
                                                                     "result_data": {"skills": ["SQL"]}}},
        ],
        "resume_versions": [
            {"key": "rv_1", "fk": {"career_profile_id": "p_a", "scan_history_id": "sh_1"},
             "v": {"resume_data": {"name": "Sam Example", "skills": ["SQL"],
                                   "roles": [{"title": "Operations Analyst", "organization": "Example Co",
                                              "bullets": ["Reported on weekly metrics."]}]}}},
        ],
        "applications": [
            {"key": "ap_1", "fk": {"career_profile_id": "p_a", "scan_history_id": "sh_1", "resume_version_id": "rv_1"},
             "v": {"job_title": "Operations Analyst", "company": "Example Co", "applied_on": "2026-02-01", "status": "applied", "notes": None}},
        ],
        "opportunities": [
            {"key": "op_1", "fk": {"career_profile_id": "p_a", "application_id": None, "approved_resume_version_id": "rv_1"},
             "v": {"title": "Operations Analyst", "employer": "Example Co", "job_url": JOB_URL_1, "dedupe_key": _sha(JOB_URL_1),
                   "location_text": "Example City", "work_arrangement": "remote", "employment_type": "full_time",
                   "base_min": 60000, "base_max": 70000, "base_period": "year", "pay_note": None, "state": "saved",
                   "dismiss_reason": None, "last_verified_on": "2026-02-02", "notes": None,
                   "approved_resume_hash": _sha("rv_1 approved"), "follow_up_on": None}},
            {"key": "op_2", "fk": {"career_profile_id": "p_a", "application_id": None, "approved_resume_version_id": None},
             "v": {"title": "Support Specialist", "employer": None, "job_url": JOB_URL_2, "dedupe_key": _sha(JOB_URL_2),
                   "location_text": None, "work_arrangement": None, "employment_type": None, "base_min": None, "base_max": None,
                   "base_period": None, "pay_note": None, "state": "dismissed", "dismiss_reason": "Not a fit",
                   "last_verified_on": None, "notes": None, "approved_resume_hash": None, "follow_up_on": None}},
        ],
        "opportunity_documents": [
            {"key": "od_1", "fk": {"opportunity_id": "op_1", "career_profile_id": "p_a", "resume_version_id": "rv_1"},
             "v": {"resume_snapshot": {"name": "Sam Example"}, "layout": "classic", "template": "standard", "ats_mode": False,
                   "renderer": "docx", "content_sha256": _sha(DOCX_FIXTURE.decode("ascii")), "docx": DOCX_FIXTURE}},
        ],
        "resume_ingestion_drafts": [
            {"key": "rd_1", "fk": {"career_profile_id": "p_a"},
             "v": {"analysis_summary": "Synthetic draft summary", "roles": [{"title": "Support Specialist", "organization": "Sample Services"}],
                   "education": [], "certifications": [], "categories": [], "history": [{"q": "Which tools did you use?", "a": "SQL"}],
                   "pending_questions": [{"id": "q1", "text": "Describe one result."}], "discovered_facts": [], "round_number": 2}},
        ],
        "job_postings": [
            {"key": "jp_1", "fk": {}, "v": {"source": "greenhouse", "board_token": "example-board", "source_job_id": "1001",
                                             "title": "Operations Analyst", "company": "Example Co", "location_text": "Example City",
                                             "work_arrangement": "remote", "employment_type": None, "job_url": JOB_URL_1,
                                             "url_hash": _sha(JOB_URL_1), "first_seen_on": date(2026, 1, 5),
                                             "last_seen_on": date(2026, 1, 20), "closed_on": None, "missing_since": None}},
        ],
        "job_preferences": [
            {"key": "jpref_1", "fk": {"career_profile_id": "p_a"},
             "v": {"target_titles": ["Operations Analyst"], "locations": ["Example City"], "remote_ok": True, "onsite_ok": False,
                   "employment_types": ["full_time"], "min_base": 50000, "exclude_words": [],
                   "followed_boards": ["greenhouse:example-board"]}},
        ],
    }


def build_manifest() -> dict[str, list[str]]:
    """table -> sorted list of row hashes computed from the synthetic records (values never stored)."""
    manifest: dict[str, list[str]] = {}
    for table in TABLE_ORDER:
        hashes = []
        for rec in synthetic_records()[table]:
            hashes.append(row_hash(table, rec["v"]))
        manifest[table] = sorted(hashes)
    return manifest


def seed_database(session: Session) -> dict[str, int]:
    """Insert the synthetic records into an EMPTY database. Refuses if any seeded table already holds rows."""
    for table in TABLE_ORDER:
        if session.execute(select(func.count()).select_from(Base.metadata.tables[table])).scalar_one():
            raise RuntimeError(f"refusing to seed: table {table} is not empty")
    records = synthetic_records()
    model_by_table = {m.class_.__tablename__: m.class_ for m in Base.registry.mappers}
    ids: dict[str, int] = {}
    counts: dict[str, int] = {}
    for table in TABLE_ORDER:
        model = model_by_table[table]
        for rec in records[table]:
            kwargs = dict(rec["v"])
            for col, logical in rec["fk"].items():
                kwargs[col] = ids[logical] if logical is not None else None
            obj = model(**kwargs)
            session.add(obj)
            session.flush()
            ids[rec["key"]] = obj.id
        counts[table] = len(records[table])
    session.commit()
    return counts


def verify_database(engine, manifest: dict[str, list[str]] | None = None) -> dict:
    """Read-only comparison of the database with the manifest. Returns aggregate counts only: no row values."""
    expected = manifest if manifest is not None else build_manifest()
    result: dict = {"tables": {}, "unexpected_tables": [], "missing_tables": []}
    read_only = engine.connect().execution_options(postgresql_readonly=True)
    try:
        present = set(_table_names(read_only))
        result["unexpected_tables"] = sorted(present - set(expected) - BOOKKEEPING_TABLES)
        result["missing_tables"] = sorted(set(expected) - present)
        for table in TABLE_ORDER:
            if table not in present:
                continue
            cols = business_columns(table)
            rows = read_only.execute(text(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"')).mappings().all()
            db_hashes = Counter(row_hash(table, dict(r)) for r in rows)
            exp = Counter(expected.get(table, []))
            matched = sum((db_hashes & exp).values())
            null_counts = {c: sum(1 for r in rows if r[c] is None) for c in cols}
            result["tables"][table] = {
                "rows": len(rows),
                "expected_rows": sum(exp.values()),
                "rows_not_in_manifest": len(rows) - matched,
                "manifest_rows_missing": sum(exp.values()) - matched,
                "null_counts": null_counts,
            }
    finally:
        read_only.close()
    result["pass"] = (
        not result["unexpected_tables"] and not result["missing_tables"]
        and all(t["rows_not_in_manifest"] == 0 and t["manifest_rows_missing"] == 0 for t in result["tables"].values())
    )
    return result


def _table_names(conn) -> list[str]:
    rows = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"))
    return [r[0] for r in rows]


def _url_for(env_name: str, expect_db_name: str) -> str:
    raw = os.environ.get(env_name, "")
    if not raw:
        raise SystemExit(f"{env_name} is not set")
    from urllib.parse import urlparse
    parts = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    name = (parts.path or "/").lstrip("/")
    if name != expect_db_name:
        raise SystemExit("refusing: database name does not match --expect-db-name")
    if name in DENY_DB_NAMES:
        raise SystemExit("refusing: database name is on the deny list")
    return raw.replace("postgresql://", "postgresql+psycopg://", 1) if raw.startswith("postgresql://") else raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic seed for a fresh database (Gate 2b).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifest", help="print the record-hash manifest (no database used)")
    p_seed = sub.add_parser("seed", help="seed an EMPTY database named by --expect-db-name")
    p_seed.add_argument("--url-env", required=True, help="environment variable holding the connection string")
    p_seed.add_argument("--expect-db-name", required=True)
    p_ver = sub.add_parser("verify", help="read-only verification against the manifest (aggregate counts only)")
    p_ver.add_argument("--url-env", required=True)
    p_ver.add_argument("--expect-db-name", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "manifest":
        print(json.dumps(build_manifest(), indent=1, sort_keys=True))
        return 0
    url = _url_for(args.url_env, args.expect_db_name)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        if args.cmd == "seed":
            with Session(engine) as session:
                counts = seed_database(session)
            print(json.dumps({"seeded_rows_per_table": counts}, sort_keys=True))
            return 0
        result = verify_database(engine)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0 if result["pass"] else 1
    except Exception as exc:  # report the class only: messages may contain data
        print(json.dumps({"error": type(exc).__name__}))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
