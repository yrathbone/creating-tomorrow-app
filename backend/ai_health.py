"""Is the AI service key actually accepted right now?

A key that is merely *set* is not enough: keys expire, get revoked or are mistyped (that is exactly what took every AI tool
down on 2026-10-08, with the old health page still saying "configured"). This asks Anthropic's free "list models" endpoint,
which spends no credit and sends none of our users' text, and reports one plain word:

    ok              the key was accepted
    rejected        the key was refused (expired, revoked or wrong)
    unreachable     could not get an answer (network trouble, timeout)
    error           the service answered with a problem that is not about the key (busy, rate limit, ...)
    not_configured  no key is set on this server

The answer is remembered for a short while so a monitor or a refreshed page cannot hammer the service. A bad answer is
remembered for less time than a good one, so a fixed key is noticed quickly. The key itself never leaves this module.
"""
import os
import threading
import time

import anthropic

from llm_utils import describe_provider_error

OK_SECONDS = 300
PROBLEM_SECONDS = 30
PROBE_TIMEOUT_SECONDS = 8.0

_lock = threading.Lock()
_remembered = {"status": None, "at": 0.0}


def probe_ai_key() -> str:
    """One real call to the AI service. Never raises."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "not_configured"
    try:
        client = anthropic.Anthropic(max_retries=0, timeout=PROBE_TIMEOUT_SECONDS)
        client.models.list(limit=1)
        return "ok"
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        print(f"[ai-key] rejected {describe_provider_error(e)}")
        return "rejected"
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        print(f"[ai-key] unreachable {describe_provider_error(e)}")
        return "unreachable"
    except anthropic.APIError as e:
        print(f"[ai-key] error {describe_provider_error(e)}")
        return "error"
    except Exception as e:  # a health check must never take the page down
        print(f"[ai-key] error class={type(e).__name__}")
        return "error"


def check_ai_key(*, force: bool = False, probe=probe_ai_key, clock=time.monotonic) -> str:
    """The key's status, from memory when it is fresh enough. `probe` and `clock` can be swapped in tests."""
    with _lock:
        status, at = _remembered["status"], _remembered["at"]
        if not force and status is not None:
            limit = OK_SECONDS if status in ("ok", "not_configured") else PROBLEM_SECONDS
            if clock() - at < limit:
                return status
        status = probe()
        _remembered["status"], _remembered["at"] = status, clock()
        return status


def forget() -> None:
    """Drops the remembered answer (tests, and a restart)."""
    with _lock:
        _remembered["status"], _remembered["at"] = None, 0.0


def log_at_startup() -> None:
    """Runs once when the server starts, off the main thread so starting is never slowed, and writes one line to the log."""
    def run():
        status = check_ai_key(force=True)
        print(f"[startup] AI key check: {status}")
    threading.Thread(target=run, name="ai-key-startup-check", daemon=True).start()
