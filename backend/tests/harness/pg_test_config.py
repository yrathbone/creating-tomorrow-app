"""Secure configuration for the disposable Neon PostgreSQL test branch (C-52 round 8).

Where the connection comes from (in this order):
1. The environment variable CT_TEST_POSTGRES_URL (set in the current shell only; nothing is written anywhere).
2. A local file outside the repository: CT_TEST_POSTGRES_ENV_FILE, or by default
   %USERPROFILE%\\.creating-tomorrow\\c52-test.env. It holds two lines:
       CT_TEST_POSTGRES_URL=postgresql://...?sslmode=require
       CT_TEST_POSTGRES_DB=<the expected database name on the test branch>
   The file is never read by git (it is outside the repository) and is never printed.

What is checked before any test runs
- Scheme is PostgreSQL, the connection requires TLS (sslmode=require or verify-full).
- The host is a Neon endpoint (*.neon.tech) and is not a Render host.
- The database name in the URL equals CT_TEST_POSTGRES_DB (the expected test database).
- A live connection reports that database name, TLS in use, and the server version.
- The server major version is reported explicitly. PostgreSQL 18 results do not establish PostgreSQL 16 compatibility.

Nothing here prints the URL, the host, or the password. Logs contain only the check results.
"""
import os
import pathlib
from urllib.parse import parse_qs, urlparse

DEFAULT_FILE = pathlib.Path(os.path.expanduser("~")) / ".creating-tomorrow" / "c52-test.env"
FORBIDDEN_HOST_PARTS = ("render.com", "onrender", "amazonaws")


class ConfigError(Exception):
    pass


def _read_env_file(path: pathlib.Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load() -> tuple[str, str]:
    """Returns (url, expected_database). Raises ConfigError with a message that never contains the URL."""
    url = os.environ.get("CT_TEST_POSTGRES_URL", "")
    expected = os.environ.get("CT_TEST_POSTGRES_DB", "")
    if not url:
        path = pathlib.Path(os.environ.get("CT_TEST_POSTGRES_ENV_FILE") or DEFAULT_FILE)
        values = _read_env_file(path)
        url = values.get("CT_TEST_POSTGRES_URL", "")
        expected = expected or values.get("CT_TEST_POSTGRES_DB", "")
    if not url:
        raise ConfigError("NOT CONFIGURED: no CT_TEST_POSTGRES_URL in the environment or the local test file.")
    p = urlparse(url)
    if p.scheme not in ("postgresql", "postgresql+psycopg"):
        raise ConfigError("REFUSED: the connection is not a PostgreSQL URL.")
    query = parse_qs(p.query)
    sslmode = (query.get("sslmode") or [""])[0]
    if sslmode not in ("require", "verify-full", "verify-ca"):
        raise ConfigError("REFUSED: the connection must require TLS (sslmode=require).")
    host = (p.hostname or "").lower()
    if not host.endswith(".neon.tech"):
        raise ConfigError("REFUSED: the host is not a Neon endpoint.")
    if any(part in host for part in FORBIDDEN_HOST_PARTS):
        raise ConfigError("REFUSED: the host belongs to a hosting platform that is not the test project.")
    db_name = (p.path or "/").lstrip("/")
    if not expected:
        raise ConfigError("REFUSED: CT_TEST_POSTGRES_DB (the expected test database name) is not set.")
    if db_name != expected:
        raise ConfigError("REFUSED: the database in the URL is not the expected test database.")
    if "prod" in db_name.lower() or "production" in db_name.lower():
        raise ConfigError("REFUSED: the database name looks like production.")
    return url, expected


def verify(url: str, expected_db: str) -> dict:
    """Connects and reports identity facts (no secrets). Raises ConfigError on any mismatch."""
    import sqlalchemy as sa
    eng = sa.create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with eng.connect() as c:
            row = c.execute(sa.text(
                "select current_database(), current_setting('server_version_num')::int, "
                "(select ssl from pg_stat_ssl where pid = pg_backend_pid())"
            )).one()
    finally:
        eng.dispose()
    db_name, version_num, ssl_on = row
    if db_name != expected_db:
        raise ConfigError("REFUSED: the live database name does not match the expected test database.")
    if not ssl_on:
        raise ConfigError("REFUSED: the live connection is not using TLS.")
    return {"database": db_name, "tls": bool(ssl_on), "server_major_version": version_num // 10000}
