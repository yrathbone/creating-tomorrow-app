"""Gate 2b: synthetic seed, record-hash manifest, relationship checks and DOCX fixtures.

Unit tests run everywhere. Database tests run ONLY against a disposable local database whose name starts with
ct_seed_disposable (set DISPOSABLE_SEED_DATABASE_URL). They never use DATABASE_URL and never touch staging or production.

Run from backend/:
  DISPOSABLE_SEED_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55544/ct_seed_disposable python -m unittest tests.test_synthetic_seed -v
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.orm import Session

from db import Base
from extractor import extract_text
from resume_builder import build_resume_bytes
import seed.synthetic_seed as seed_mod
from seed.synthetic_seed import (
    FIXTURE_DIR, RESUME_A, RESUME_B, TABLE_ORDER, _url_for, all_columns, build_manifest, full_rows, row_hash,
    seed_database, synthetic_records, verify_database,
)

BACKEND = Path(__file__).resolve().parents[1]
MANIFEST_FILE = BACKEND / "seed" / "synthetic_manifest.json"
RESERVED = ("@example.com", "@example.invalid", "@example.org")
URL_ENV = "DISPOSABLE_SEED_DATABASE_URL"
BLOCKLIST = ("gmail", "creatingtomorrow")  # generic. The founder keeps a private list of real names and checks locally; none is recorded here.


def _ids(table):
    return {r["id"] for r in synthetic_records()[table]}


class SeedContent(unittest.TestCase):
    def test_order_covers_every_table_exactly_once(self):
        self.assertEqual(sorted(TABLE_ORDER), sorted(Base.metadata.tables.keys()))
        self.assertEqual(len(TABLE_ORDER), len(set(TABLE_ORDER)))

    def test_every_row_gives_every_column_an_explicit_value(self):
        rows = full_rows()
        for table in TABLE_ORDER:
            cols = set(all_columns(table))
            self.assertTrue(rows[table], f"{table} has no synthetic row")
            for row in rows[table]:
                self.assertEqual(set(row), cols, f"{table} row {row.get('id')} does not give every column a value")

    def test_timestamps_are_fixed_values_not_database_defaults(self):
        rows = full_rows()
        for table in TABLE_ORDER:
            for col in Base.metadata.tables[table].columns:
                if isinstance(col.type, DateTime):
                    for row in rows[table]:
                        value = row[col.name]
                        self.assertTrue(value is None or isinstance(value, datetime), f"{table}.{col.name} is not fixed")
                        if value is None:
                            self.assertIn(col.name, {"deleted_at", "consent_given_at", "missing_since"},
                                          f"{table}.{col.name} is NULL but not an intentional NULL")

    def test_foreign_keys_point_to_fixed_parent_rows_seeded_earlier(self):
        seen = {table: set() for table in TABLE_ORDER}
        for table in TABLE_ORDER:
            for row in full_rows()[table]:
                for fk in Base.metadata.tables[table].foreign_keys:
                    value = row[fk.parent.name]
                    if value is not None:
                        parent = fk.column.table.name
                        self.assertIn(value, seen[parent], f"{table}.{fk.parent.name}={value} is not an earlier {parent} row")
                seen[table].add(row["id"])

    def test_linked_rows_belong_to_the_same_profile(self):
        rows = full_rows()
        profile_of = {"career_profiles": {r["id"]: r["id"] for r in rows["career_profiles"]}}
        for table in TABLE_ORDER:
            if table == "career_profiles":
                continue
            for row in rows[table]:
                if "career_profile_id" in row:
                    profile_of.setdefault(table, {})[row["id"]] = row["career_profile_id"]
        for table in TABLE_ORDER:
            for row in rows[table]:
                for fk in Base.metadata.tables[table].foreign_keys:
                    parent = fk.column.table.name
                    if "career_profile_id" in row and row[fk.parent.name] is not None and parent in profile_of:
                        self.assertEqual(profile_of[parent][row[fk.parent.name]], row["career_profile_id"],
                                         f"{table} row {row['id']} is linked to another profile through {fk.parent.name}")

    def test_second_member_has_linked_data_in_every_profile_table(self):
        rows = full_rows()
        for table in ("experiences", "skills", "education", "languages", "scan_histories", "resume_versions",
                      "applications", "opportunities", "opportunity_documents", "resume_ingestion_drafts", "job_preferences"):
            self.assertTrue([r for r in rows[table] if r.get("career_profile_id") == 202 or r.get("opportunity_id") == 1103],
                            f"{table} has no row for the second member")

    def test_job_postings_cover_the_statuses_the_screens_show(self):
        rows = full_rows()["job_postings"]
        self.assertTrue([r for r in rows if r["closed_on"] is None and r["missing_since"] is None], "no open posting")
        self.assertTrue([r for r in rows if r["missing_since"] is not None and r["closed_on"] is None], "no missing posting")
        self.assertTrue([r for r in rows if r["closed_on"] is not None], "no closed posting")
        self.assertEqual({r["source"] for r in rows}, {"greenhouse", "ashby"})
        self.assertEqual({r["work_arrangement"] for r in rows if r["work_arrangement"]}, {"remote", "hybrid", "on_site"})
        for r in rows:
            self.assertGreaterEqual(r["last_seen_on"], r["first_seen_on"])

    def test_every_email_is_on_a_reserved_test_domain_or_null(self):
        for row in full_rows()["users"]:
            self.assertTrue(row["email"] is None or row["email"].endswith(RESERVED))

    def test_every_url_is_a_placeholder_domain(self):
        for table in ("opportunities", "job_postings"):
            for row in full_rows()[table]:
                self.assertTrue(row["job_url"].startswith("https://jobs.example.com/"))

    def test_no_real_person_names_or_contacts_in_seed_or_fixtures(self):
        blob = json.dumps(synthetic_records(), default=str).lower()
        for docx in FIXTURE_DIR.glob("*.docx"):
            blob += extract_text(docx.name, docx.read_bytes()).lower()
        for word in BLOCKLIST:
            self.assertNotIn(word, blob, f"seed or fixture contains {word!r}")


class DocxFixtures(unittest.TestCase):
    def test_committed_docx_files_parse_and_contain_the_fictional_content(self):
        text_a = extract_text("synthetic_resume_sam_example.docx", (FIXTURE_DIR / "synthetic_resume_sam_example.docx").read_bytes())
        for needle in ("Sam Example", "Operations Analyst", "Example Co", "Support Specialist", "Intern, Data Team", "Reported on weekly service metrics"):
            self.assertIn(needle, text_a)
        text_b = extract_text("synthetic_resume_riley_sample.docx", (FIXTURE_DIR / "synthetic_resume_riley_sample.docx").read_bytes())
        for needle in ("Riley Sample", "Project Coordinator", "Sample Services", "Coordinated four field schedules"):
            self.assertIn(needle, text_b)

    def test_the_app_renders_the_same_resume_data_into_a_parseable_docx(self):
        rendered = build_resume_bytes(RESUME_A, ats_mode=False, template="classic")
        self.assertTrue(rendered.startswith(b"PK"), "a DOCX is a zip package")
        self.assertIn("Sam Example", extract_text("rendered.docx", rendered))

    def test_recorded_content_hash_matches_the_fixture_bytes(self):
        for row in full_rows()["opportunity_documents"]:
            self.assertEqual(row["content_sha256"], hashlib.sha256(row["docx"]).hexdigest())

    def test_docx_fixtures_are_not_placeholders(self):
        for docx in FIXTURE_DIR.glob("*.docx"):
            self.assertGreater(docx.stat().st_size, 10_000, f"{docx.name} is too small to be a real document")


class ManifestAndGuards(unittest.TestCase):
    def test_manifest_is_deterministic(self):
        self.assertEqual(build_manifest(), build_manifest())

    def test_stored_manifest_matches_the_generated_one(self):
        stored = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        self.assertEqual(stored, build_manifest(), "run: python -m seed.synthetic_seed manifest > seed/synthetic_manifest.json")

    def test_manifest_holds_hashes_only(self):
        for hashes in build_manifest().values():
            for h in hashes:
                self.assertRegex(h, r"^[0-9a-f]{64}$")

    def test_one_changed_value_changes_the_row_hash(self):
        row = dict(full_rows()["experiences"][0])
        before = row_hash("experiences", row)
        self.assertNotEqual(before, row_hash("experiences", dict(row, title="Operations Analyst II")))
        self.assertNotEqual(before, row_hash("experiences", dict(row, career_profile_id=202)), "a changed parent link must change the hash")

    def test_a_missing_column_is_an_error_not_a_silent_null(self):
        row = dict(full_rows()["experiences"][0])
        del row["title"]
        with self.assertRaises(KeyError):
            row_hash("experiences", row)

    def test_database_name_guard(self):
        os.environ["SEED_TEST_URL"] = "postgresql+psycopg://example-user@example-host:1/ct_seed_disposable"
        try:
            self.assertTrue(_url_for("SEED_TEST_URL", "ct_seed_disposable").endswith("/ct_seed_disposable"))
            with self.assertRaises(SystemExit):
                _url_for("SEED_TEST_URL", "some_other_name")
            os.environ["SEED_TEST_URL"] = "postgresql+psycopg://example-user@example-host/creating-tomorrow-staging-db"
            with self.assertRaises(SystemExit):
                _url_for("SEED_TEST_URL", "creating-tomorrow-staging-db")
        finally:
            del os.environ["SEED_TEST_URL"]


def _disposable_url():
    raw = os.environ[URL_ENV]
    parts = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    name = (parts.path or "/").lstrip("/")
    if parts.hostname not in ("localhost", "127.0.0.1") or not name.startswith("ct_seed_disposable"):
        raise RuntimeError("refusing: the URL must be a ct_seed_disposable* database on localhost")
    return raw


@unittest.skipUnless(os.environ.get(URL_ENV), f"set {URL_ENV} to a disposable local database")
class SeedAgainstDisposableDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = _disposable_url()
        cls.engine = create_engine(cls.url, pool_pre_ping=True)
        with cls.engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        env = dict(os.environ, DATABASE_URL=cls.url)
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as conn:
            for table in reversed(TABLE_ORDER):
                conn.execute(text(f'DELETE FROM "{table}"'))

    def _seeded(self):
        with Session(self.engine) as s:
            seed_database(s)

    def test_migrations_reach_head_on_an_empty_database(self):
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0012")

    def test_seed_then_verify_passes_with_zero_mismatches_and_zero_link_problems(self):
        self._seeded()
        result = verify_database(self.engine)
        self.assertTrue(result["pass"], {k: v for k, v in result.items() if k != "tables"})
        for table, stats in result["tables"].items():
            self.assertEqual((stats["rows_not_in_manifest"], stats["manifest_rows_missing"]), (0, 0), table)
        for rel, stats in result["relationships"].items():
            self.assertEqual(stats["orphans"], 0, rel)
            self.assertIn(stats["cross_profile"], (None, 0), rel)

    def test_sequences_continue_after_the_fixed_ids(self):
        self._seeded()
        with self.engine.begin() as conn:
            new_id = conn.execute(text("INSERT INTO users (cognito_sub) VALUES ('synthetic-sub-9999') RETURNING id")).scalar_one()
            conn.execute(text("DELETE FROM users WHERE id = :i"), {"i": new_id})
        self.assertGreater(new_id, 103)

    def test_seed_refuses_a_database_that_already_has_rows(self):
        self._seeded()
        with Session(self.engine) as s:
            with self.assertRaises(RuntimeError):
                seed_database(s)

    def test_a_tampered_row_is_counted_as_a_mismatch(self):
        self._seeded()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE experiences SET title = 'Tampered Title' WHERE id = 301"))
        result = verify_database(self.engine)
        self.assertFalse(result["pass"])
        self.assertEqual(result["tables"]["experiences"]["rows_not_in_manifest"], 1)
        self.assertEqual(result["tables"]["experiences"]["manifest_rows_missing"], 1)

    def test_a_row_attached_to_the_wrong_profile_is_detected(self):
        self._seeded()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE experiences SET career_profile_id = 202 WHERE id = 301"))
        result = verify_database(self.engine)
        self.assertFalse(result["pass"])
        self.assertEqual(result["tables"]["experiences"]["rows_not_in_manifest"], 1)

    def test_a_cross_profile_foreign_key_is_counted(self):
        self._seeded()
        with self.engine.begin() as conn:
            # Skill 403 belongs to profile 202; pointing it at experience 301 (profile 201) is a cross-profile link.
            conn.execute(text("UPDATE skills SET experience_id = 301 WHERE id = 403"))
        result = verify_database(self.engine)
        self.assertFalse(result["pass"])
        self.assertEqual(result["relationships"]["skills.experience_id->experiences.id"]["cross_profile"], 1)

    def test_a_non_synthetic_email_is_counted_as_a_mismatch(self):
        self._seeded()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE users SET email = 'not.synthetic@gmail.com' WHERE id = 102"))
        result = verify_database(self.engine)
        self.assertFalse(result["pass"])
        self.assertEqual(result["tables"]["users"]["rows_not_in_manifest"], 1)

    def test_seeded_document_bytes_are_the_committed_fixtures(self):
        self._seeded()
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT id, docx FROM opportunity_documents ORDER BY id")).all()
        self.assertEqual(bytes(rows[0].docx), (FIXTURE_DIR / "synthetic_resume_sam_example.docx").read_bytes())
        self.assertEqual(bytes(rows[1].docx), (FIXTURE_DIR / "synthetic_resume_riley_sample.docx").read_bytes())

    def test_verify_changes_nothing(self):
        self._seeded()
        def snapshot():
            with self.engine.connect() as conn:
                return {t: conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in TABLE_ORDER}
        before = snapshot()
        verify_database(self.engine)
        self.assertEqual(snapshot(), before)

    def test_verify_output_has_no_row_values(self):
        self._seeded()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE experiences SET title = 'Tampered Title' WHERE id = 301"))
        blob = json.dumps(verify_database(self.engine), default=str)
        for value in ("Tampered Title", "Operations Analyst", "Example Co", "member@example.invalid", "Sam Example", "SQL"):
            self.assertNotIn(value, blob)


if __name__ == "__main__":
    unittest.main()
