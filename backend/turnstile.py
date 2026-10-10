"""
Cloudflare Turnstile: the invisible "is this a person's browser?" check in front of the public AI tools (risk-audit finding F-01).

How it works: the tool page gets a short-lived, single-use token from Cloudflare and sends it in the X-Turnstile-Token header. The
abuse guard (abuse_guard.py) asks Cloudflare, with our secret key, whether the token is genuine, and only then lets the request
reach the AI. No valid token, no AI call, no cost.

The check is OFF until BOTH keys are set (TURNSTILE_SITE_KEY, public, shown to the browser; TURNSTILE_SECRET_KEY, private, only ever
in Render's settings). With either missing, everything behaves exactly as before, so the code can be deployed before the keys exist.
If Cloudflare cannot be reached the tools say so and ask the visitor to try again (they never open up to everyone).
The token and the secret are never logged.
"""
import asyncio
import json
import os
import urllib.parse
import urllib.request

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TOKEN_HEADER = "x-turnstile-token"
MAX_TOKEN_LENGTH = 2048          # Cloudflare's documented maximum
VERIFY_TIMEOUT_SECONDS = 5
DEFAULT_HOSTNAMES = "creatingtomorrow.net,www.creatingtomorrow.net"

FAILED_MESSAGE = ("We couldn't confirm that you're a person. Please reload the page and try again. "
                  "If you use a privacy or ad blocker, please allow challenges.cloudflare.com for this site.")
UNAVAILABLE_MESSAGE = "The check that keeps bots out is not answering right now. Please try again in a minute."


def _secret() -> str | None:
    return os.environ.get("TURNSTILE_SECRET_KEY", "").strip() or None


def site_key() -> str | None:
    return os.environ.get("TURNSTILE_SITE_KEY", "").strip() or None


def enabled() -> bool:
    """On only when both keys are set: a secret without a site key would lock every visitor out."""
    return bool(_secret() and site_key())


def public_config() -> dict:
    """What the browser may know: whether the check is on, and the PUBLIC site key. Never the secret."""
    return {"enabled": enabled(), "site_key": site_key() if enabled() else None}


def _allowed_hostnames() -> set[str]:
    raw = os.environ.get("TURNSTILE_ALLOWED_HOSTNAMES", DEFAULT_HOSTNAMES)
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def verify(token: str) -> tuple[bool, str]:
    """Ask Cloudflare whether a token is genuine. Returns (ok, reason) with reason one of 'ok', 'invalid', 'unreachable'."""
    secret = _secret()
    if not secret:
        return True, "ok"
    body = urllib.parse.urlencode({"secret": secret, "response": token}).encode()
    request = urllib.request.Request(SITEVERIFY_URL, data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=VERIFY_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        return False, "unreachable"
    if not isinstance(result, dict) or result.get("success") is not True:
        return False, "invalid"
    hostname = str(result.get("hostname") or "").lower()
    if hostname and hostname not in _allowed_hostnames():
        return False, "invalid"      # a token earned on some other website
    return True, "ok"


async def verify_async(token: str) -> tuple[bool, str]:
    return await asyncio.to_thread(verify, token)
