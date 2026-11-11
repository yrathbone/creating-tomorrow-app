"""Secure configuration for the disposable Neon PostgreSQL test branch c52-test (C-52 round 9).

Source (first match wins):
1. Environment variables (current shell only).
2. A local file outside the repository: CT_TEST_POSTGRES_ENV_FILE, or by default
   %USERPROFILE%\\.creating-tomorrow\\c52-test.env. Never read by git; never printed.

Required settings (names only; values are never printed):
  CT_TEST_POSTGRES_URL       direct connection string for the c52-test branch (TLS required)
  CT_TEST_NEON_ENDPOINT      the endpoint identifier of the c52-test branch, copied from the Neon dashboard (ep-...)
  CT_TEST_POSTGRES_DB        the database name on that branch (for example neondb)
  CT_TEST_DISPOSABLE_CONFIRMED=yes   the founder confirms this database is disposable and holds no real member data
Optional:
  CT_TEST_NEON_REGION        default us-east-2
  CT_TEST_PG_MAJOR           default 18 (the server major version the run must report)

Checks before any test or migration runs
- TLS is required (sslmode=require or verify-full).
- The host is <endpoint>.<region>.aws.neon.tech with the expected endpoint identifier and region. Any other host is refused.
- The host and database name must not contain "prod", and no Render host is accepted.
- The URL database equals CT_TEST_POSTGRES_DB.
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
    url = _setting("CT_TEST_POSTGRES_URL", fv)
    endpoint = _setting("CT_TEST_NEON_ENDPOINT", fv).lower()
    region = _setting("CT_TEST_NEON_REGION", fv, "us-east-2").lower()
    expected_db = _setting("CT_TEST_POSTGRES_DB", fv)
    confirmed = _setting("CT_TEST_DISPOSABLE_CONFIRMED", fv).lower()
    major = int(_setting("CT_TEST_PG_MAJOR", fv, "18"))
    missing = [n for n, v in (("CT_TEST_POSTGRES_URL", url), ("CT_TEST_NEON_ENDPOINT", endpoint),
                              ("CT_TEST_POSTGRES_DB", expected_db)) if not v]
    if missing:
        raise ConfigError("NOT CONFIGURED: missing " + ", ".join(missing) + " (in the environment or the local test file).")
    if confirmed != "yes":
        raise ConfigError("REFUSED: CT_TEST_DISPOSABLE_CONFIRMED=yes is required (the founder confirms the database is disposable).")
    if not endpoint.startswith("ep-"):
        raise ConfigError("REFUSED: the endpoint identifier must be a Neon endpoint identifier (ep-...).")
    p = urlparse(url)
    if p.scheme not in ("postgresql", "postgresql+psycopg"):
        raise ConfigError("REFUSED: the connection is not a PostgreSQL URL.")
    sslmode = (parse_qs(p.query).get("sslmode") or [""])[0]
    if sslmode not in ("require", "verify-full", "verify-ca"):
        raise ConfigError("REFUSED: the connection must require TLS (sslmode=require or verify-full).")
    host = (p.hostname or "").lower()
    expected_host_suffix = f".{region}.aws.neon.tech"
    if not host.endswith(expected_host_suffix):
        raise ConfigError("REFUSED: the host is not a Neon host in the expected region.")
    if host.split(".")[0] != endpoint:
        raise ConfigError("REFUSED: the host's endpoint identifier is not the c52-test endpoint identifier.")
    if any(f in host for f in FORBIDDEN_FRAGMENTS):
        raise ConfigError("REFUSED: the host contains a name that belongs to production or to a hosting platform.")
    db_name = (p.path or "/").lstrip("/")
    if db_name != expected_db:
        raise ConfigError("REFUSED: the database in the URL is not the expected database.")
    if any(f in db_name.lower() for f in FORBIDDEN_FRAGMENTS):
        raise ConfigError("REFUSED: the database name looks like production.")
    return {"url": url, "database": expected_db, "endpoint": endpoint, "major": major}


def verify(cfg: dict) -> dict:
    """Connects with TLS and checks the database name, TLS state, and server major version. Prints no secrets."""
    import sqlalchemy as sa
    eng = sa.create_engine(cfg["url"].replace("postgresql://", "postgresql+psycopg://", 1), connect_args={"connect_timeout": 15})
    try:
        with eng.connect() as c:
            row = c.execute(sa.text(
                "select current_database(), current_setting('server_version_num')::int, "
                "(select ssl from pg_stat_ssl where pid = pg_backend_pid())"
            )).one()
    finally:
        eng.dispose()
    db_name, version_num, ssl_on = row
    if db_name != cfg["database"]:
        raise ConfigError("REFUSED: the live database name does not match the expected database.")
    if not ssl_on:
        raise ConfigError("REFUSED: the live connection is not using TLS.")
    major = version_num // 10000
    if major != cfg["major"]:
        raise ConfigError(f"REFUSED: the server reports PostgreSQL {major}, expected {cfg['major']}.")
    return {"database": db_name, "tls": True, "server_major_version": major}
