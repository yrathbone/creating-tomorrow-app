"""PostgreSQL migration checks for C-52 (0010 and 0011). Runs only against the configured disposable Neon test branch.

Configuration and identity checks live in tests/harness/pg_test_config.py. Nothing runs unless the configuration passes, and
the connection string is never printed. Results for PostgreSQL 18 do not establish PostgreSQL 16 compatibility.

Checks: upgrade to head, downgrade to 0009, re-upgrade; the opportunities and opportunity_documents tables exist.
"""
import os
import subprocess
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "tests", "harness"))
import pg_test_config  # noqa: E402

try:
    CFG = pg_test_config.load()
    URL, EXPECTED_DB = CFG["url"], CFG["database"]
    VERIFIED = pg_test_config.verify(CFG)
    SKIP_REASON = ""
except pg_test_config.ConfigError as e:
    CFG, URL, EXPECTED_DB, VERIFIED = None, "", "", None
    SKIP_REASON = str(e)


@unittest.skipUnless(VERIFIED is not None, "NOT RUN: " + SKIP_REASON)
class PostgresMigrationCycle(unittest.TestCase):
    def _alembic(self, *args):
        env = dict(os.environ, DATABASE_URL=URL)
        return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, check=True)

    def test_upgrade_downgrade_reupgrade(self):
        self._alembic("upgrade", "head")
        self._alembic("downgrade", "0010")
        self._alembic("downgrade", "0009")
        self._alembic("upgrade", "head")

    def test_tables_present_after_upgrade(self):
        self._alembic("upgrade", "head")
        import sqlalchemy as sa
        eng = sa.create_engine(URL.replace("postgresql://", "postgresql+psycopg://", 1))
        with eng.connect() as c:
            names = {r[0] for r in c.execute(sa.text("select table_name from information_schema.tables where table_schema='public'"))}
        eng.dispose()
        self.assertIn("opportunities", names)
        self.assertIn("opportunity_documents", names)


if __name__ == "__main__":
    unittest.main()
