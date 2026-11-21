"""Gate 2b: synthetic seed and record-hash manifest.

Unit tests run everywhere. Database tests run ONLY against a disposable local database whose name starts with
ct_seed_disposable (set DISPOSABLE_SEED_DATABASE_URL). They never use DATABASE_URL and never touch staging or production.

Run from backend/:
  DISPOSABLE_SEED_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55545/ct_seed_disposable python -m unittest tests.test_synthetic_seed -v
"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db import Base
import seed.synthetic_seed as seed_mod
from seed.synthetic_seed import (
    TABLE_ORDER, build_manifest, business_columns, row_hash, seed_database, synthetic_records, verify_database,
)

BACKEND = Path(__file__).resolve().parents[1]
MANIFEST_FILE = BACKEND / "seed" / "synthetic_manifest.json"
RESERVED = ("@example.com", "@example.invalid", "@example.org")
URL_ENV = "DISPOSABLE_SEED_DATABASE_URL"


class SyntheticFixtureCoverage(unittest.TestCase):
    def test_order_covers_every_table_exactly_once(self):
        self.assertEqual(sorted(TABLE_ORDER), sorted(Base.metadata.tables.keys()))
        self.assertEqual(len(TABLE_ORDER), len(set(TABLE_ORDER)))

    def test_every_business_column_has_an_explicit_value_in_every_record(self):
        records = synthetic_records()
        for table in TABLE_ORDER:
            cols = set(business_columns(table))
            self.assertTrue(records[table], f"{table} has no synthetic record")
            for rec in records[table]:
                self.assertEqual(set(rec["v"]), cols, f"{table}/{rec['key']} does not give every business column a value")

    def test_foreign_keys_refer_to_earlier_records(self):
        records = synthetic_records()
        seen = set()
        for table in TABLE_ORDER:
            for rec in records[table]:
                for logical in rec["fk"].values():
                    if logical is not None:
                        self.assertIn(logical, seen, f"{table}/{rec['key']} refers to a record not seeded before it")
                seen.add(rec["key"])

    def test_every_email_is_on_a_reserved_test_domain_or_null(self):
        for rec in synthetic_records()["users"]:
            email = rec["v"]["email"]
            self.assertTrue(email is None or email.endswith(RESERVED), "email outside the reserved test domains")

    def test_every_url_is_a_placeholder_domain(self):
        for table in ("opportunities", "job_postings"):
            for rec in synthetic_records()[table]:
                url = rec["v"]["job_url"]
                self.assertTrue(url.startswith("https://jobs.example.com/"), "job URL is not on the placeholder domain")

    def test_no_real_looking_person_names_in_the_seed(self):
        blob = json.dumps(synthetic_records(), default=str).lower()
        for name in ("marcus", "bell", "yovana", "rathbone", "jo ", "gmail"):
            self.assertNotIn(name, blob, f"seed contains {name!r}")


class ManifestDeterminism(unittest.TestCase):
    def test_manifest_is_deterministic(self):
        self.assertEqual(build_manifest(), build_manifest())

    def test_stored_manifest_matches_the_generated_one(self):
        stored = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        self.assertEqual(stored, build_manifest(), "run: python -m seed.synthetic_seed manifest > seed/synthetic_manifest.json")

    def test_one_changed_value_changes_the_row_hash(self):
        rec = synthetic_records()["experiences"][0]
        before = row_hash("experiences", rec["v"])
        changed = dict(rec["v"], title="Operations Analyst II")
        self.assertNotEqual(before, row_hash("experiences", changed))

    def test_a_missing_column_is_an_error_not_a_silent_null(self):
        rec = dict(synthetic_records()["experiences"][0]["v"])
        del rec["title"]
        with self.assertRaises(KeyError):
            row_hash("experiences", rec)

    def test_manifest_holds_hashes_only(self):
        for table, hashes in build_manifest().items():
            for h in hashes:
                self.assertRegex(h, r"^[0-9a-f]{64}$")


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

    def test_migrations_reach_head_on_an_empty_database(self):
        with self.engine.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(rev, "0012")

    def test_seed_then_verify_passes_with_zero_mismatches(self):
        with Session(self.engine) as s:
            counts = seed_database(s)
        self.assertEqual(counts, {t: len(synthetic_records()[t]) for t in TABLE_ORDER})
        result = verify_database(self.engine)
        self.assertTrue(result["pass"], result)
        for table, stats in result["tables"].items():
            self.assertEqual(stats["rows_not_in_manifest"], 0, table)
            self.assertEqual(stats["manifest_rows_missing"], 0, table)

    def test_seed_refuses_a_database_that_already_has_rows(self):
        with Session(self.engine) as s:
            seed_database(s)
        with Session(self.engine) as s:
            with self.assertRaises(RuntimeError):
                seed_database(s)

    def test_a_tampered_row_is_counted_as_a_mismatch(self):
        with Session(self.engine) as s:
            seed_database(s)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE experiences SET title = 'Tampered Title' WHERE title = 'Operations Analyst'"))
        result = verify_database(self.engine)
        self.assertFalse(result["pass"])
        self.assertEqual(result["tables"]["experiences"]["rows_not_in_manifest"], 1)
        self.assertEqual(result["tables"]["experiences"]["manifest_rows_missing"], 1)

    def test_a_non_synthetic_email_is_counted_as_a_mismatch(self):
        with Session(self.engine) as s:
            seed_database(s)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE users SET email = 'not.synthetic@gmail.com' WHERE cognito_sub = 'synthetic-sub-0002'"))
        result = verify_database(self.engine)
        self.assertFalse(result["pass"])
        self.assertEqual(result["tables"]["users"]["rows_not_in_manifest"], 1)

    def test_verify_changes_nothing(self):
        with Session(self.engine) as s:
            seed_database(s)
        def snapshot():
            with self.engine.connect() as conn:
                return {t: conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in TABLE_ORDER}
        before = snapshot()
        verify_database(self.engine)
        self.assertEqual(snapshot(), before)

    def test_verify_output_has_no_row_values(self):
        with Session(self.engine) as s:
            seed_database(s)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE experiences SET title = 'Tampered Title' WHERE title = 'Operations Analyst'"))
        blob = json.dumps(verify_database(self.engine), default=str)
        for value in ("Tampered Title", "Operations Analyst", "Example Co", "member@example.invalid"):
            self.assertNotIn(value, blob)


if __name__ == "__main__":
    unittest.main()
