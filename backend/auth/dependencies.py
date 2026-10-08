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


def _issuer() -> str:
    return f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"


def _fetch_jwks() -> dict:
    url = f"{_issuer()}/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read())


def _get_signing_key(kid: str) -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        _jwks_cache = _fetch_jwks()
    for key in _jwks_cache.get("keys", []):
        if key.get("kid") == kid:
            return key
    # kid not found - could be genuine key rotation, refetch once before giving up.
    _jwks_cache = _fetch_jwks()
    for key in _jwks_cache.get("keys", []):
        if key.get("kid") == kid:
            return key
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
