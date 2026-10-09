"""Protection against runaway use of the paid AI tools, and against oversized requests.

Why this exists: nine public endpoints call the paid AI service for anyone, with no sign-in. Before this, nothing limited
how often one visitor (or one script) could call them. The risk-audit findings F-01, F-03 and F-04 are addressed here:

  * Per-visitor limits (per minute, hour and day) on the public AI tools, by the visitor's real address.
  * A global ceiling per hour and per day across all visitors, so even if someone hides their address, the AI bill
    has a limit.
  * A cap on how many AI calls can run at the same time, so a burst cannot tie up the server.
  * Per-account limits on the signed-in AI routes.
  * A size limit on every upload or form (and a small one on JSON bodies), checked while the request streams in,
    before the whole body is read into memory.

Limits are kept in memory. The site runs one worker, so they are exact; if it ever runs several workers, each keeps its
own count (so the real limit is a multiple). Every number can be changed with an environment setting, with no code change.
The visitor's address comes from Cloudflare's CF-Connecting-IP header (Render's edge is Cloudflare, so a visitor
cannot forge it). X-Forwarded-For is ignored on purpose: Render appends to it instead of replacing it, so it can be forged.
"""
import hashlib
import ipaddress
import os
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException
from starlette.responses import JSONResponse

from auth.dependencies import get_current_user

PUBLIC_AI_PATHS = frozenset({
    "/api/analyze", "/api/refine", "/api/elevate-start", "/api/elevate-discover", "/api/elevate-finalize",
    "/api/profile-review", "/api/prepare", "/api/scratch-entry", "/api/scratch-finalize",
})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

DEFAULTS = {
    # Per visitor address: per minute, hour, day. Generous on purpose: a classroom or a library shares ONE address.
    "RATE_LIMIT_PUBLIC_IP": "10/60,100/3600,300/86400",
    "RATE_LIMIT_PUBLIC_GLOBAL": "300/3600,1500/86400",       # all visitors together: the ceiling on the AI bill
    "RATE_LIMIT_USER": "10/60,60/3600,300/86400",            # per signed-in account
}
DEFAULT_MAX_CONCURRENT_AI = 8
DEFAULT_MAX_JSON_BYTES = 2 * 1024 * 1024            # 2 MB: JSON bodies here are small
DEFAULT_MAX_UPLOAD_BYTES = 60 * 1024 * 1024         # 60 MB: the largest legitimate form (screenshots + PDF + resume)

RATE_MESSAGE = "You've used the free tools a lot in a short time. Please wait a few minutes and try again."
BUSY_MESSAGE = "Our tools are busy right now. Please try again in a minute."
TOO_LARGE_MESSAGE = "That upload is too large."


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
        return value if value > 0 else default
    except ValueError:
        return default


def rules_from_env(name: str) -> list[tuple[int, int]]:
    """'6/60,40/3600' -> [(6, 60), (40, 3600)] meaning at most 6 per 60 seconds and 40 per 3600. Bad text falls back to the default."""
    def parse(text):
        out = []
        for part in text.split(","):
            limit, window = part.strip().split("/")
            limit, window = int(limit), int(window)
            if limit < 1 or window < 1:
                raise ValueError
            out.append((limit, window))
        return out
    try:
        return parse(os.environ.get(name) or DEFAULTS[name])
    except (ValueError, AttributeError):
        return parse(DEFAULTS[name])


class SlidingWindowLimiter:
    """Counts hits per key inside rolling time windows. A refused hit is not counted, so a blocked visitor is freed as soon as the oldest hit ages out."""
    MAX_KEYS = 20000

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str, rules: list[tuple[int, int]], now: float | None = None) -> tuple[bool, int]:
        """Records a hit and returns (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        longest = max(window for _, window in rules)
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= longest:
                hits.popleft()
            wait = 0
            for limit, window in rules:
                recent = [t for t in hits if now - t < window]
                if len(recent) >= limit:
                    wait = max(wait, int(window - (now - recent[-limit])) + 1)
            if wait:
                return False, wait
            hits.append(now)
            if len(self._hits) > self.MAX_KEYS:
                self._prune(now, longest)
            return True, 0

    def _prune(self, now: float, longest: float) -> None:
        for k in [k for k, h in self._hits.items() if not h or now - h[-1] >= longest]:
            del self._hits[k]
        if len(self._hits) > self.MAX_KEYS:  # still too many live keys: drop the least recently active tenth
            oldest = sorted(self._hits, key=lambda k: self._hits[k][-1])[: self.MAX_KEYS // 10]
            for k in oldest:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class InFlight:
    """How many AI calls are running right now."""
    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._n >= _int_env("MAX_CONCURRENT_AI", DEFAULT_MAX_CONCURRENT_AI):
                return False
            self._n += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._n = max(0, self._n - 1)

    @property
    def count(self) -> int:
        return self._n

    def reset(self) -> None:
        with self._lock:
            self._n = 0


LIMITER = SlidingWindowLimiter()
IN_FLIGHT = InFlight()


def reset() -> None:
    """For tests."""
    LIMITER.reset()
    IN_FLIGHT.reset()


def client_key(headers: dict, client) -> str:
    """The visitor's address as a rate-limit key. IPv6 visitors are grouped by their /64 (one household or device owns a whole /64)."""
    raw = None
    if headers.get("cf-ray") and headers.get("cf-connecting-ip"):
        raw = headers["cf-connecting-ip"].strip()
    elif client:
        raw = client[0]
    try:
        ip = ipaddress.ip_address(raw)
    except (ValueError, TypeError):
        return "unknown"
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _short(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _json(status: int, detail: str, retry_after: int | None = None) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


class _TooLarge(BaseException):
    """Not an Exception subclass on purpose: FastAPI turns any Exception raised while reading a body into a generic 400; this must reach the middleware that sends the 413."""


class AbuseGuardMiddleware:
    """Pure ASGI middleware: size limits on every body-carrying request, and rate limits plus a concurrency cap on the public AI tools."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method, path = scope["method"], scope["path"]

        # ---- size ----
        max_bytes = None
        if method in BODY_METHODS:
            multipart = headers.get("content-type", "").lower().startswith("multipart/form-data")
            max_bytes = _int_env("MAX_UPLOAD_REQUEST_BYTES", DEFAULT_MAX_UPLOAD_BYTES) if multipart else _int_env("MAX_JSON_REQUEST_BYTES", DEFAULT_MAX_JSON_BYTES)
            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                return await _json(413, TOO_LARGE_MESSAGE)(scope, receive, send)

        # ---- rate limits and concurrency (public AI tools only) ----
        slot = False
        if method == "POST" and path in PUBLIC_AI_PATHS:
            key = client_key(headers, scope.get("client"))
            allowed, wait = LIMITER.check(f"ip:{key}", rules_from_env("RATE_LIMIT_PUBLIC_IP"))
            if allowed:
                allowed, wait = LIMITER.check("global:public-ai", rules_from_env("RATE_LIMIT_PUBLIC_GLOBAL"))
            if not allowed:
                print(f"[abuse] rate limit on {path} visitor={_short(key)} retry_after={wait}s")
                return await _json(429, RATE_MESSAGE, wait)(scope, receive, send)
            if not IN_FLIGHT.acquire():
                print(f"[abuse] busy on {path}")
                return await _json(503, BUSY_MESSAGE, 30)(scope, receive, send)
            slot = True

        started = False
        total = 0

        async def counted_receive():
            nonlocal total
            message = await receive()
            if max_bytes is not None and message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > max_bytes:
                    raise _TooLarge()
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive if max_bytes is not None else receive, tracked_send)
        except _TooLarge:
            if not started:
                await _json(413, TOO_LARGE_MESSAGE)(scope, receive, send)
        finally:
            if slot:
                IN_FLIGHT.release()


def user_ai_guard(current_user=Depends(get_current_user)):
    """FastAPI dependency for the signed-in AI routes: a per-account rate limit and a place in the shared concurrency cap."""
    key = f"user:{current_user.id}"
    allowed, wait = LIMITER.check(key, rules_from_env("RATE_LIMIT_USER"))
    if not allowed:
        print(f"[abuse] account rate limit retry_after={wait}s")
        raise HTTPException(status_code=429, detail=RATE_MESSAGE, headers={"Retry-After": str(wait)})
    if not IN_FLIGHT.acquire():
        raise HTTPException(status_code=503, detail=BUSY_MESSAGE, headers={"Retry-After": "30"})
    try:
        yield current_user
    finally:
        IN_FLIGHT.release()
