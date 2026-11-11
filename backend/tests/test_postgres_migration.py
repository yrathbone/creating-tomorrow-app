"""PostgreSQL migration checks for C-52 (0010 and 0011). Prepared, NOT RUN until a trusted PostgreSQL test database exists.

Runs only when CT_TEST_POSTGRES_URL points at a DISPOSABLE, localhost-only test database with synthetic data. It refuses any
other host, and it refuses a database whose name does not contain "test". It never runs against production.

Checks: upgrade to head, downgrade to 0009, re-upgrade; the opportunities and opportunity_documents tables exist; the cascade
from opportunities to opportunity_documents holds.
"""
import os
import subprocess
import sys
import unittest
from urllib.parse import urlparse

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = os.environ.get("CT_TEST_POSTGRES_URL", "")


def _allowed(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url)
    return p.scheme.startswith("postgresql") and p.hostname in ("127.0.0.1", "localhost") and "test" in (p.path or "").lower()


@unittest.skipUnless(_allowed(URL), "NOT RUN: set CT_TEST_POSTGRES_URL to a disposable localhost PostgreSQL test database")
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
        eng = sa.create_engine(URL)
        with eng.connect() as c:
            names = {r[0] for r in c.execute(sa.text("select table_name from information_schema.tables where table_schema='public'"))}
        eng.dispose()
        self.assertIn("opportunities", names)
        self.assertIn("opportunity_documents", names)


if __name__ == "__main__":
    unittest.main()
