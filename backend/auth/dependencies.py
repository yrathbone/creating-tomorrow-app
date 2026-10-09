"""
Cognito access-token verification - the "internal interface" from
docs/CAREER_PROFILE_ARCHITECTURE_AUDIT.md Decision 1 / Deliverable C.

Every protected route depends on get_current_user() and only ever sees the
returned internal User object - never a raw Cognito token or claim. If the
auth provider ever changes, only this module needs to change.

Verifies the Cognito ACCESS token, not the ID token (Decision 12) - the
access token authorizes calls to a resource server (this API); the ID
token is for the frontend's own display use and is never sent here. The
access token carries `sub` and `client_id` but no `aud` claim (that's an
ID-token-only field), so audience verification is disabled and client_id
is checked explicitly instead - both per Deliverable C's verified design.
"""
import json
import os
import time
import urllib.request

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import get_db_session
from models import User

COGNITO_REGION = os.environ.get("COGNITO_REGION")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID")
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID")

_bearer = HTTPBearer(auto_error=True)

_jwks_cache: dict | None = None
_jwks_fetched_at: float | None = None      # when the key list was last fetched (None: planted by hand, never expires)
_jwks_last_attempt: float | None = None    # when we last tried to fetch (success or not)
_unknown_kids: dict[str, float] = {}       # key ids we looked for and did not find, and when

JWKS_MAX_AGE_SECONDS = 6 * 3600     # re-read Cognito's key list at least this often
JWKS_MIN_REFETCH_SECONDS = 60       # never ask Cognito again sooner than this because of an unknown key id
UNKNOWN_KID_SECONDS = 300           # remember "not found" for a key id this long
MAX_REMEMBERED_UNKNOWN_KIDS = 1000


def _issuer() -> str:
    return f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"


def _fetch_jwks() -> dict:
    url = f"{_issuer()}/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def _refresh_jwks() -> None:
    """Fetch Cognito's published keys. If that fails and we already have keys, keep using them (a short outage must not sign everyone out)."""
    global _jwks_cache, _jwks_fetched_at, _jwks_last_attempt
    _jwks_last_attempt = time.monotonic()
    try:
        _jwks_cache = _fetch_jwks()
        _jwks_fetched_at = _jwks_last_attempt
    except Exception:
        if _jwks_cache is None:
            raise HTTPException(status_code=503, detail="Couldn't reach the sign-in service. Please try again in a moment.")


def _find_key(kid: str) -> dict | None:
    for key in (_jwks_cache or {}).get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def _get_signing_key(kid: str) -> dict:
    """The public key for a token's key id. Cached; an unknown id triggers at most one refetch a minute, and is remembered
    as unknown for a few minutes, so forged tokens cannot make this server hammer Cognito (risk-audit finding F-06)."""
    now = time.monotonic()
    if _jwks_cache is None or (_jwks_fetched_at is not None and now - _jwks_fetched_at > JWKS_MAX_AGE_SECONDS):
        _refresh_jwks()
    key = _find_key(kid)
    if key:
        return key
    if now - _unknown_kids.get(kid, -1e9) < UNKNOWN_KID_SECONDS:
        raise JWTError("Signing key not found in Cognito's published JWKS.")
    # could be genuine key rotation: refetch, but not more than once a minute
    if _jwks_last_attempt is None or now - _jwks_last_attempt >= JWKS_MIN_REFETCH_SECONDS:
        _refresh_jwks()
        key = _find_key(kid)
        if key:
            return key
    if len(_unknown_kids) >= MAX_REMEMBERED_UNKNOWN_KIDS:
        _unknown_kids.clear()
    _unknown_kids[kid] = now
    raise JWTError("Signing key not found in Cognito's published JWKS.")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db_session),
) -> User:
    if not COGNITO_REGION or not COGNITO_USER_POOL_ID or not COGNITO_APP_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Authentication is not configured on this server.")

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        signing_key = _get_signing_key(header["kid"])
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=_issuer(),
            options={"verify_aud": False},
        )
    except (JWTError, KeyError) as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token.") from e

    if claims.get("token_use") != "access":
        raise HTTPException(status_code=401, detail="An access token is required, not an ID token.")
    if claims.get("client_id") != COGNITO_APP_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Token was not issued for this application.")

    cognito_sub = claims.get("sub")
    if not cognito_sub:
        raise HTTPException(status_code=401, detail="Token is missing a subject claim.")

    user = db.query(User).filter_by(cognito_sub=cognito_sub).one_or_none()
    if user is None:
        user = User(cognito_sub=cognito_sub)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Two first requests from the same new person raced and the other one created
            # the row first (cognito_sub is unique). Use theirs instead of failing with a 500.
            db.rollback()
            user = db.query(User).filter_by(cognito_sub=cognito_sub).one()
        else:
            db.refresh(user)
    if user.deleted_at is not None:
        raise HTTPException(status_code=403, detail="This account is no longer active.")
    return user
