"""Secure configuration for the disposable self-hosted PostgreSQL test database used by C-52.

Source (first match wins):
1. Environment variables (current shell only).
2. A local file outside the repository: CT_TEST_POSTGRES_ENV_FILE, or by default
   %USERPROFILE%\\.creating-tomorrow\\c52-test.env. Never read by git; never printed.

Required settings (names only; values are never printed):
  CT_TEST_HOST_MODE=selfhosted       explicit opt-in; any other value (or none) is refused
  CT_TEST_POSTGRES_URL               connection string for the test database (TLS required)
  CT_TEST_SELFHOSTED_HOST            the exact host name or private IP of the test instance
  CT_TEST_POSTGRES_DB                the test database name (must be marked as the C-52 test database, for example ct_c52_test)
  CT_TEST_DISPOSABLE_CONFIRMED=yes   the founder confirms this database is disposable and holds no real member data
Optional:
  CT_TEST_PG_MAJOR                   default 16 (the server major version the run must report)

Checks before any test or migration runs
- The mode must be selfhosted.
- TLS is required (sslmode=require, verify-ca or verify-full).
- The host must equal CT_TEST_SELFHOSTED_HOST exactly. No suffix or wildcard matching.
- The host and database name must not contain "prod", "production", or a hosting-platform name (render).
- The database name must be the configured one, and must be marked as the C-52 test database (contains "c52" and "test").
- A live connection reports the same database name, TLS in use, and the expected server major version.

Output contains only check results and the reported version. The URL, host, user, and password are never printed.
"""
import os
import pathlib
from urllib.parse import parse_qs, urlparse

DEFAULT_FILE = pathlib.Path(os.path.expanduser("~")) / ".creating-tomorrow" / "c52-test.env"
FORBIDDEN_FRAGMENTS = ("render", "onrender", "prod", "production")


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


def _setting(name: str, file_values: dict, default: str = "") -> str:
    return os.environ.get(name) or file_values.get(name, "") or default


def load() -> dict:
    """Returns the validated settings. Raises ConfigError with a message that never contains a secret."""
    path = pathlib.Path(os.environ.get("CT_TEST_POSTGRES_ENV_FILE") or DEFAULT_FILE)
    fv = _read_env_file(path)
    if _setting("CT_TEST_HOST_MODE", fv).lower() != "selfhosted":
        raise ConfigError("REFUSED: CT_TEST_HOST_MODE=selfhosted is required (explicit opt-in for the C-52 test database).")
    url = _setting("CT_TEST_POSTGRES_URL", fv)
    expected_host = _setting("CT_TEST_SELFHOSTED_HOST", fv).lower()
    expected_db = _setting("CT_TEST_POSTGRES_DB", fv)
    confirmed = _setting("CT_TEST_DISPOSABLE_CONFIRMED", fv).lower()
    major = int(_setting("CT_TEST_PG_MAJOR", fv, "16"))
    if not (url and expected_host and expected_db):
        raise ConfigError("NOT CONFIGURED: missing CT_TEST_POSTGRES_URL, CT_TEST_SELFHOSTED_HOST or CT_TEST_POSTGRES_DB (in the environment or the local test file).")
    if confirmed != "yes":
        raise ConfigError("REFUSED: CT_TEST_DISPOSABLE_CONFIRMED=yes is required (the founder confirms the database is disposable).")
    p = urlparse(url)
    if p.scheme not in ("postgresql", "postgresql+psycopg"):
        raise ConfigError("REFUSED: the connection is not a PostgreSQL URL.")
    sslmode = (parse_qs(p.query).get("sslmode") or [""])[0]
    if sslmode not in ("require", "verify-full", "verify-ca"):
        raise ConfigError("REFUSED: the connection must require TLS (sslmode=require, verify-ca or verify-full).")
    host = (p.hostname or "").lower()
    if host != expected_host:
        raise ConfigError("REFUSED: the host is not the configured self-hosted test host.")
    if any(f in host for f in FORBIDDEN_FRAGMENTS):
        raise ConfigError("REFUSED: the host contains a name that belongs to production or to a hosting platform.")
    db_name = (p.path or "/").lstrip("/")
    if db_name != expected_db:
        raise ConfigError("REFUSED: the database in the URL is not the expected database.")
    if any(f in db_name.lower() for f in FORBIDDEN_FRAGMENTS):
        raise ConfigError("REFUSED: the database name looks like production.")
    if not ("c52" in db_name.lower() and "test" in db_name.lower()):
        raise ConfigError("REFUSED: the database name must mark it as the C-52 test database.")
    return {"url": url, "database": expected_db, "endpoint": host, "major": major}


def verify(cfg: dict) -> dict:
    """Connects with TLS and checks the database name, TLS state, and server major version. Prints no secrets."""
    import sqlalchemy as sa
    eng = sa.create_engine(cfg["url"].replace("postgresql://", "postgresql+psycopg://", 1), connect_args={"connect_timeout": 15})
    try:
        with eng.connect() as c:
            # Client-side TLS state from the driver (authoritative for this connection).
            client_tls = bool(c.connection.driver_connection.pgconn.ssl_in_use)
            row = c.execute(sa.text(
                "select current_database(), current_setting('server_version_num')::int, "
                "(select ssl from pg_stat_ssl where pid = pg_backend_pid())"
            )).one()
    finally:
        eng.dispose()
    db_name, version_num, server_ssl = row
    ssl_on = client_tls
    if db_name != cfg["database"]:
        raise ConfigError("REFUSED: the live database name does not match the expected database.")
    if not ssl_on:
        raise ConfigError("REFUSED: the live connection is not using TLS.")
    major = version_num // 10000
    if major != cfg["major"]:
        raise ConfigError(f"REFUSED: the server reports PostgreSQL {major}, expected {cfg['major']}.")
    return {"database": db_name, "tls": True, "server_major_version": major}
