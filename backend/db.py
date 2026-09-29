"""
SQLAlchemy engine/session setup for the Career Profile feature's database.

Phase-scoped: this module makes the database connection available and
proves it works end to end (see check_connection() and /api/health in
main.py). It does not yet back any user-facing feature - see
docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md for the full design this is the
first slice of.

DATABASE_URL is optional at import time so the app keeps working exactly as
before wherever it isn't set (local dev without a database, e.g. the
frontend-static/backend-full .claude/launch.json configs) - the same
lazy-check pattern already used for ANTHROPIC_API_KEY elsewhere in this
codebase. It's only required once something actually tries to use the
database.
"""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def normalized_database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    # Render provides a plain postgresql:// URL; this project uses psycopg
    # (v3, not psycopg2 - see requirements.txt), which SQLAlchemy needs
    # told explicitly via the postgresql+psycopg:// dialect prefix.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        url = normalized_database_url()
        if not url:
            raise RuntimeError("DATABASE_URL is not set on this environment.")
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine())
    return _SessionLocal()


def check_connection() -> None:
    """Runs a trivial query to confirm the database is reachable. Raises on failure. Synchronous/blocking - callers on the event loop should run this via run_in_threadpool, same as every other blocking call in this codebase."""
    session = get_session()
    try:
        session.execute(text("SELECT 1"))
    finally:
        session.close()
