"""What to tell people, and what to do, when the AI service refuses or cannot answer (proposal P7).

Before, every failure of the AI service became "We couldn't complete this ... right now. Please try again." (HTTP 502). That is
misleading when the monthly spending limit has been reached: trying again cannot work until the allowance renews, and a person
who keeps clicking only adds failing requests. Anthropic's documented shapes (platform.claude.com/docs/en/api/errors and
/rate-limits, retrieved 2026-11-01):
  * a spend limit you set:  HTTP 400, type invalid_request_error, message "You have reached your specified API usage limits ..."
  * the plan's own cap:     HTTP 429, type rate_limit_error, details.error_code "enforced_spend_limit_reached", no retry-after
  * billing problem:        HTTP 402, type billing_error (an empty prepaid balance has also been reported as a 400 "credit balance" message;
                            not confirmed in the pages read, so both are handled)
  * overloaded: 529; server trouble 500/502/503/504; plain rate limit: 429 with retry-after; bad key or model: 401/403/404.

Everything here looks only at status codes, error types and the first words of Anthropic's own message. It never sees or logs
anything a person typed. While the allowance is spent ("paused") the app answers at once, without calling the AI service, and
the health pages report it so an uptime monitor can alert the owner.
"""
import os
import re
import time

from fastapi import HTTPException

PAUSE_KINDS = ("spend_limit", "billing")
DEFAULT_PAUSE_SECONDS = 15 * 60
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

PAUSED_MESSAGE = (
    "Our AI helper has used this month's free-service budget, so this step is paused. Your work is still here and nothing "
    "was lost. You can still edit your profile and download the resumes you have already made. The AI steps will be back "
    "when the monthly allowance renews{when}. Creating Tomorrow runs on a small budget so it can stay free."
)
BUSY_MESSAGE = "Our AI helper is busy right now. Please wait a minute and try again. Your work is still here."
CONFIG_MESSAGE = "This tool is temporarily unavailable. We have been told and are looking into it. Your work is still here."

_clock = time.monotonic
_state = {"until": 0.0, "kind": None, "resume_on": None}


def _error_parts(e):
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    message = " ".join(str(err.get("message") or getattr(e, "message", "") or "").split())
    return getattr(e, "status_code", None), err.get("type"), details.get("error_code"), message


def classify_provider_error(e) -> str:
    """spend_limit | billing | rate_limited | busy | config | other"""
    status, etype, code, message = _error_parts(e)
    lowered = message.lower()
    if code == "enforced_spend_limit_reached":
        return "spend_limit"
    if status in (400, 429) and "reached your specified" in lowered and "usage limit" in lowered:
        return "spend_limit"
    if status == 402 or etype == "billing_error" or (status == 400 and "credit balance" in lowered):
        return "billing"
    if status == 429 or etype == "rate_limit_error":
        return "rate_limited"
    if status in (500, 502, 503, 504, 529) or etype in ("overloaded_error", "api_error", "timeout_error"):
        return "busy"
    if status is None and type(e).__name__ in ("APIConnectionError", "APITimeoutError"):
        return "busy"
    if status in (401, 403) or etype in ("authentication_error", "permission_error") or (status == 404 and etype == "not_found_error"):
        return "config"
    return "other"


def _pause_seconds() -> int:
    try:
        value = int(os.environ.get("AI_PAUSE_SECONDS", "") or DEFAULT_PAUSE_SECONDS)
        return value if value > 0 else DEFAULT_PAUSE_SECONDS
    except ValueError:
        return DEFAULT_PAUSE_SECONDS


def paused_message(resume_on=None) -> str:
    return PAUSED_MESSAGE.format(when=f" on {resume_on}" if resume_on else "")


def _pause(kind: str, message: str) -> None:
    found = _ISO_DATE.search(message or "")
    _state.update(until=_clock() + _pause_seconds(), kind=kind, resume_on=found.group(1) if found else None)
    print(f"[ai-paused] kind={kind} for {_pause_seconds()}s")


def pause_state():
    """None while the AI service is usable, else {"kind", "seconds_left", "message"}."""
    left = _state["until"] - _clock()
    if left <= 0:
        return None
    return {"kind": _state["kind"], "seconds_left": int(left) + 1, "message": paused_message(_state["resume_on"])}


def reset() -> None:
    """For tests."""
    _state.update(until=0.0, kind=None, resume_on=None)


def pause_response_parts():
    """(status, message, headers) for a request refused because the allowance is spent, or None."""
    state = pause_state()
    if state is None:
        return None
    return 503, state["message"], {"Retry-After": str(state["seconds_left"]), "X-AI-Status": "paused"}


def _walk(e):
    seen = 0
    while e is not None and seen < 5:
        yield e
        e = e.__cause__
        seen += 1


def ai_failure(e) -> HTTPException:
    """The HTTP answer for a tool's own error `e` (JobMatchError, CoachError, ...). The tool raised it `from` the provider's
    exception, so the real reason is on `__cause__`. Anything unrecognised keeps the old 502 and the tool's own wording."""
    for candidate in _walk(e):
        kind = classify_provider_error(candidate)
        if kind == "other":
            continue
        if kind in PAUSE_KINDS:
            _pause(kind, _error_parts(candidate)[3])
            status, message, headers = pause_response_parts()
            return HTTPException(status_code=status, detail=message, headers=headers)
        if kind == "config":
            print(f"[ai-config] the AI service refused our credentials or model (status={getattr(candidate, 'status_code', '?')})")
            return HTTPException(status_code=503, detail=CONFIG_MESSAGE, headers={"X-AI-Status": "unavailable"})
        retry_after = "30"
        headers = getattr(getattr(candidate, "response", None), "headers", None)
        if headers is not None and str(headers.get("retry-after", "")).isdigit():
            retry_after = str(headers.get("retry-after"))
        return HTTPException(status_code=503, detail=BUSY_MESSAGE, headers={"Retry-After": retry_after, "X-AI-Status": "busy"})
    return HTTPException(status_code=502, detail=str(e))
