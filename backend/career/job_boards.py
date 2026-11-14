"""Job discovery pilot: approved employer boards, central fetch, strict parsing, and the rules that protect live postings.

Feature switch: CT_JOB_DISCOVERY_ENABLED (default off). Nothing here runs unless the switch is on AND the run is started by
hand (job_discovery_run.py). Boards come only from the approved registry career/job_boards.json; no member can add a URL.

Protections (founder requirement 5: failed, partial or malformed responses must never close active postings):
- A board is read once per run for all members (central fetch).
- Only HTTP 200 with a JSON object and a list of jobs counts as a response. Redirects are refused. Responses over the byte limit
  (2 MB Greenhouse, 5 MB Ashby, read in bounded chunks) or with more than 5000 jobs are refused. Anything else is "held": nothing for that board changes.
- Postings are closed only when the response is complete, the malformed share is at most 20%, and the response is not an empty
  list while postings were open (an empty list is held for founder review, not closed).
- If the open count falls below 20% of the previous open count (with at least 5 open before), closing is held.
- A posting closes only after two complete runs at least 20 hours apart (UTC). Calendar dates alone never decide closing.
- Closing cap: a board may close at most max(1, 20% of its open postings) in one run. A bigger batch closes nothing that run;
  marks and reappearance clearing still apply. The cap blocks closures only.
- Each board is written in its own transaction; an error rolls back that board only.
- Closed postings are deleted 14 days after closing.

Data kept: metadata only (see models.JobPosting). No description, compensation text, department or office list is requested
or stored. The apply link is checked with the same URL rules as saved links (career/opportunities.normalize_job_url), and it is
never fetched by the app.
"""
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from career.opportunities import normalize_job_url
from models import JobPosting

logger = logging.getLogger("creating_tomorrow.job_boards")

REGISTRY_PATH = Path(__file__).with_name("job_boards.json")
SOURCE_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
TIMEOUT_SECONDS = 10
MAX_BYTES = 2_000_000          # Greenhouse: no descriptions requested, so 2 MB is ample
ASHBY_MAX_BYTES = 5_000_000    # Ashby: every item carries descriptionHtml/descriptionPlain. Measured 1,960,620 bytes for
                               # Plaid (143 jobs) on 2026-11-12, so 5 MB leaves about 2.5x headroom. Never above 10 MB.
MAX_BYTES_BY_SOURCE = {"greenhouse": MAX_BYTES, "ashby": ASHBY_MAX_BYTES}
MAX_JOBS = 5000
MAX_MALFORMED_SHARE = 0.2
RETENTION_DAYS = 14
MIN_HOURS_MISSING_BEFORE_CLOSE = 20  # a posting must stay missing from complete runs for at least this long (UTC) before it closes
CLOSING_CAP_DIVISOR = 5              # closing cap = 1/5 (20%) of the board's open postings before the run
MIN_CLOSING_CAP = 1                  # ...and never less than 1, so small boards are protected too
DROP_CHECK_MIN_OPEN = 5
DROP_CHECK_MIN_SHARE = 0.2
USER_AGENT = "CreatingTomorrow-pilot/1.0"
ASHBY_WORKPLACE = {"onsite": "on_site", "remote": "remote", "hybrid": "hybrid"}
ASHBY_EMPLOYMENT = {"fulltime": "full_time", "parttime": "part_time", "contract": "contract", "temporary": "temporary", "intern": "internship"}


class BoardError(Exception):
    """A board response that must not change anything (held)."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a redirect becomes an HTTPError, which is held


_OPENER = urllib.request.build_opener(_NoRedirects)


def board_key(board: dict) -> str:
    return f"{board['source']}:{board['board_token']}"


def load_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise BoardError("the board registry must be a list")
    boards = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise BoardError("each registry entry must be an object")
        source, token = entry.get("source"), entry.get("board_token")
        if source not in SOURCE_URLS or not isinstance(token, str) or not TOKEN_PATTERN.match(token):
            raise BoardError("registry entry has an unsupported source or board token")
        if entry.get("enabled", True) is not True:
            continue
        boards.append({"source": source, "board_token": token, "name": str(entry.get("name") or token)[:120]})
    keys = [board_key(b) for b in boards]
    if len(set(keys)) != len(keys):
        raise BoardError("the registry lists a board twice")
    return boards


def fetch_payload(board: dict, opener=None):
    url = SOURCE_URLS[board["source"]].format(token=board["board_token"])
    limit = MAX_BYTES_BY_SOURCE[board["source"]]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with (opener or _OPENER).open(req, timeout=TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                raise BoardError(f"HTTP {resp.status}")
            declared = resp.headers.get("Content-Length") if getattr(resp, "headers", None) is not None else None
            if declared is not None and declared.isdigit() and int(declared) > limit:
                raise BoardError("response too large")  # refused before reading the body
            body = _read_bounded(resp, limit)
    except urllib.error.HTTPError as e:
        raise BoardError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise BoardError("network error") from None
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        # a truncated or malformed body is held here, never partly used
        raise BoardError("response is not valid JSON or is incomplete") from None


def _read_bounded(resp, limit: int) -> bytes:
    """Reads in chunks and stops as soon as the byte limit is passed. Nothing beyond the limit is kept."""
    chunks, total = [], 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise BoardError("response too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _text(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())[:limit]
    return value or None


def _record(board: dict, job_id, title, location, url, arrangement, employment) -> dict | None:
    job_id = str(job_id).strip() if isinstance(job_id, (str, int)) and not isinstance(job_id, bool) else ""
    title = _text(title, 300)
    if not job_id or len(job_id) > 200 or not title:
        return None
    try:
        stored_url, url_hash = normalize_job_url(url)
    except Exception:  # a link that fails the saved-link rules is skipped, never repaired
        return None
    return {
        "source_job_id": job_id,
        "title": title,
        "company": board["name"][:200],
        "location_text": _text(location, 300),
        "work_arrangement": arrangement,
        "employment_type": employment,
        "job_url": stored_url,
        "url_hash": url_hash,
    }


def parse_greenhouse(payload, board: dict) -> tuple[list[dict], int]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise BoardError("unexpected Greenhouse response shape")
    if len(jobs) > MAX_JOBS:
        raise BoardError("too many jobs in one response")
    records, malformed = [], 0
    for job in jobs:
        if not isinstance(job, dict):
            malformed += 1
            continue
        loc = job.get("location")
        location = loc.get("name") if isinstance(loc, dict) else None
        rec = _record(board, job.get("id"), job.get("title"), location, job.get("absolute_url"), None, None)
        if rec is None:
            malformed += 1
        else:
            records.append(rec)
    return records, malformed


def parse_ashby(payload, board: dict) -> tuple[list[dict], int]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise BoardError("unexpected Ashby response shape")
    if len(jobs) > MAX_JOBS:
        raise BoardError("too many jobs in one response")
    records, malformed = [], 0
    for job in jobs:
        if not isinstance(job, dict):
            malformed += 1
            continue
        if job.get("isListed") is False:  # direct-link only: not on the public board, so not offered
            continue
        url = job.get("jobUrl") or job.get("applyUrl")
        workplace = str(job.get("workplaceType") or "").strip().lower()
        arrangement = ASHBY_WORKPLACE.get(workplace)
        if arrangement is None and job.get("isRemote") is True:
            arrangement = "remote"
        employment = ASHBY_EMPLOYMENT.get(str(job.get("employmentType") or "").strip().lower().replace("_", "").replace("-", ""))
        job_id = job.get("id") if job.get("id") is not None else url  # the public API may omit id: the link identifies the posting
        rec = _record(board, job_id, job.get("title"), job.get("location"), url, arrangement, employment)
        if rec is None:
            malformed += 1
        else:
            records.append(rec)
    return records, malformed


PARSERS = {"greenhouse": parse_greenhouse, "ashby": parse_ashby}


def fetch_board_records(board: dict, opener=None) -> tuple[list[dict], int]:
    payload = fetch_payload(board, opener)
    return PARSERS[board["source"]](payload, board)


def as_utc(value: datetime) -> datetime:
    """Timestamps are stored and compared in UTC. SQLite returns naive datetimes, so a naive value is read as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def apply_board_records(db, board: dict, records: list[dict], malformed: int, now: datetime) -> dict:
    """Write one board's result. Returns counts only (no titles, no links).

    `now` must be timezone-aware. Calendar dates stored on rows are the UTC date of `now`; the closing rule compares elapsed
    time in UTC, so the local timezone of the machine that runs the job has no effect on when a posting closes.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = as_utc(now)
    today = now.date()
    counts = {"added": 0, "updated": 0, "duplicate_skipped": 0, "closed": 0, "missing_once": 0, "close_held": "",
              "cap_held": "", "cap_blocked": 0, "held_rows_untouched": 0}
    existing = {p.source_job_id: p for p in db.query(JobPosting).filter_by(source=board["source"], board_token=board["board_token"]).all()}
    open_before = sum(1 for p in existing.values() if p.closed_on is None)
    total = len(records) + malformed

    if total and malformed / total > MAX_MALFORMED_SHARE:
        counts["close_held"] = "too many malformed jobs in this response"
    elif not records and open_before:
        counts["close_held"] = "empty list while postings were open (founder review)"
    elif open_before >= DROP_CHECK_MIN_OPEN and len(records) < DROP_CHECK_MIN_SHARE * open_before:
        counts["close_held"] = "sharp drop in open postings (founder review)"

    seen = set()
    for rec in records:
        seen.add(rec["source_job_id"])
        row = existing.get(rec["source_job_id"])
        clash = db.query(JobPosting).filter(JobPosting.url_hash == rec["url_hash"])
        if row is not None:
            clash = clash.filter(JobPosting.id != row.id)
        if clash.first() is not None:
            counts["duplicate_skipped"] += 1  # the same apply link is already listed under another key
            continue
        if row is None:
            db.add(JobPosting(
                source=board["source"], board_token=board["board_token"], source_job_id=rec["source_job_id"],
                title=rec["title"], company=rec["company"], location_text=rec["location_text"],
                work_arrangement=rec["work_arrangement"], employment_type=rec["employment_type"],
                job_url=rec["job_url"], url_hash=rec["url_hash"], first_seen_on=today, last_seen_on=today, closed_on=None,
            ))
            counts["added"] += 1
        else:
            if counts["close_held"]:
                # A whole-run hold may not change an existing row at all: no mark set or cleared, no closed_on, no dates.
                counts["held_rows_untouched"] += 1
                continue
            row.title, row.company, row.location_text = rec["title"], rec["company"], rec["location_text"]
            row.work_arrangement, row.employment_type = rec["work_arrangement"], rec["employment_type"]
            row.job_url, row.url_hash = rec["job_url"], rec["url_hash"]
            row.last_seen_on, row.closed_on, row.missing_since = today, None, None  # seen again: open again, no longer missing
            counts["updated"] += 1

    # Two-run confirmation with a minimum gap. A posting missing from a complete run is only marked (missing_since, UTC).
    # It closes on a later complete run once at least MIN_HOURS_MISSING_BEFORE_CLOSE hours have passed since the mark.
    # The mark is set and cleared only by complete runs; a whole-run hold changes no mark. Nothing closes in the run that sets a mark.
    # Closing cap (closures only): if more postings would close on this run than closing_cap(open_before) allows, no posting on
    # this board closes in this run. Marks are still set on newly missing postings, and reappearing postings still lose their mark.
    if not counts["close_held"]:
        mature = [row for source_job_id, row in existing.items()
                  if row.closed_on is None and source_job_id not in seen and row.missing_since is not None
                  and now - as_utc(row.missing_since) >= timedelta(hours=MIN_HOURS_MISSING_BEFORE_CLOSE)]
        cap = closing_cap(open_before)
        cap_blocks = len(mature) > cap
        if cap_blocks:
            counts["cap_held"] = f"closing cap: {len(mature)} eligible, limit {cap}"
            counts["cap_blocked"] = len(mature)
        for source_job_id, row in existing.items():
            if row.closed_on is None and source_job_id not in seen:
                if row.missing_since is None:
                    row.missing_since = now
                    counts["missing_once"] += 1
                elif not cap_blocks and now - as_utc(row.missing_since) >= timedelta(hours=MIN_HOURS_MISSING_BEFORE_CLOSE):
                    row.closed_on = today
                    counts["closed"] += 1
    return counts


def closing_cap(open_before: int) -> int:
    """Most postings one board may close in one run: 20% of its open postings before the run, and never less than 1.
    Integer arithmetic (20% = one fifth), so small boards get the floor of 1 and large boards 20%."""
    return max(MIN_CLOSING_CAP, open_before // CLOSING_CAP_DIVISOR)


def purge_closed(db, today: date) -> int:
    cutoff = today - timedelta(days=RETENTION_DAYS)
    return db.query(JobPosting).filter(JobPosting.closed_on.is_not(None), JobPosting.closed_on < cutoff).delete(synchronize_session=False)


def run_sync(db, now: datetime, registry: list[dict] | None = None, opener=None) -> dict:
    """Central run: each approved board is read once. Returns a report with counts and reasons only.

    `now` must be timezone-aware (the runner passes datetime.now(timezone.utc)).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = as_utc(now)
    today = now.date()
    boards = registry if registry is not None else load_registry()
    report = {"date": today.isoformat(), "run_at_utc": now.isoformat(), "boards": []}
    for board in boards:
        entry = {"board": board_key(board)}
        try:
            records, malformed = fetch_board_records(board, opener)
            entry.update(apply_board_records(db, board, records, malformed, now))
            entry["result"] = "ok"
            db.commit()
        except BoardError as e:
            db.rollback()
            entry["result"], entry["reason"] = "held", str(e)
        except Exception:
            db.rollback()
            entry["result"], entry["reason"] = "error", "unexpected error (see server log)"
            logger.exception("job board sync failed for %s", board_key(board))
        report["boards"].append(entry)
    report["purged"] = purge_closed(db, today)
    db.commit()
    return report
