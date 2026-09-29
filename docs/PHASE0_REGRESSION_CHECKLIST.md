# Phase 0 Regression Checklist

Written **before** any Phase 0 change was made, per the approved
acceptance requirements. Purpose: confirm Phase 0's CORS tightening and
additive-only backend changes don't break any of the six existing
anonymous tools. This is a lean smoke test (one real, minimal request
per tool), not a full QA pass — the project already has a much more
exhaustive test suite from an earlier session; this checklist exists
specifically to catch a Phase 0 regression, not to re-verify everything
this project already knows works.

## What's being tested and why

Phase 0 touches: `backend/main.py`'s CORS configuration, and two new,
additive-only files (`backend/resume_ingestion.py`,
`backend/requirements.txt` additions). None of the six tools' own code
changes. The realistic regression risk is narrow and specific:
**CORS tightening from `allow_origins=["*"]` to an explicit origin list
could reject a legitimate request if the list is wrong or incomplete.**
Everything else in Phase 0 is additive (new unused files, new unused
dependencies) and has no plausible mechanism to break existing behavior.

## Local development origin, documented

`.claude/launch.json` (`D:\NP\.claude\launch.json`) defines two local
dev configurations:
- `backend-full` (port 8124) — serves frontend and API from the same
  origin (no CORS involved at all, same-origin).
- `frontend-static` (port 8123) — serves *only* the frontend, separately
  from the API.

The one scenario that actually exercises CORS locally is running
`frontend-static` (`http://localhost:8123`) while it calls the API on
`backend-full` (`http://localhost:8124`) — a genuine cross-origin
request under this project's own existing tooling. **This is the
"documented local-development origin" referenced in the Phase 0
acceptance requirements: `http://localhost:8123`.**

## Checklist — one minimal real request per tool

| # | Tool | Action | Expected result |
|---|---|---|---|
| 1 | Beginning | `POST /api/scratch-entry` with a minimal real entry | 200, `drafted_bullets` + `reflective_questions` present |
| 2 | Refine | `POST /api/refine` with a real resume file | 200, `resume_data` present |
| 3 | Right Fit | `POST /api/analyze` with a real resume file + job posting | 200, `match_report` present |
| 4 | Elevate | `POST /api/elevate-start` with a real resume file | 200, `resume_data` + `questions` present |
| 5 | Spotlight | `POST /api/profile-review` with pasted profile text | 200, review fields present |
| 6 | Prepare | `POST /api/prepare` with a job description | 200, `employer_priorities` present |
| 7 | (shared) | `POST /api/generate` with a minimal `resume_data` | 200, valid `.docx` bytes returned |
| 8 | (shared) | `GET /` (homepage) and `GET /tool.html` | 200, static frontend still served |
| 9 | (shared) | `GET /api/health` | 200, `{"status": "ok", ...}` |
| 10 | CORS | `OPTIONS`/`GET` against `/api/health` with `Origin: https://creatingtomorrow.net`, `Origin: https://www.creatingtomorrow.net`, and `Origin: http://localhost:8123` | Each returns an `Access-Control-Allow-Origin` header matching that origin |
| 11 | CORS (negative) | Same, with `Origin: https://evil-example.com` | No matching `Access-Control-Allow-Origin` header for this origin |

## Results

Run twice: once locally (before pushing) and once against production
(`https://creatingtomorrow.net`, after the deploy was confirmed live via
the new CORS behavior, not just a passing health check — the app's own
known "health check passing ≠ new code fully live" gotcha).

| # | Check | Local | Production |
|---|---|---|---|
| 1 | Beginning | PASS | PASS |
| 2 | Refine | PASS | PASS |
| 3 | Right Fit | PASS | PASS |
| 4 | Elevate | PASS | PASS |
| 5 | Spotlight | PASS | PASS |
| 6 | Prepare | FAIL then PASS on retry (see note) | PASS |
| 7 | `/api/generate` | PASS | PASS |
| 8 | Static pages | PASS | PASS |
| 9 | `/api/health` | PASS | PASS |
| 10 | CORS, 3 allowed origins | PASS | PASS |
| 11 | CORS, negative case | PASS | PASS |

**Note on item 6 (local run only):** the first local Prepare call
returned a 502 (`missing_required_field` on both the original attempt
and the automatic retry, per `prepare.py`'s own logged diagnostic). This
is a real finding, but **not a Phase 0 regression** — `prepare.py` was
not touched by any Phase 0 change, and an immediate retry of the exact
same request succeeded (200). Logged as a pre-existing, rare
reliability edge case worth a look before Phase 1, not something Phase
0 caused or should fix (out of this phase's scope). Production ran
Prepare successfully on the first attempt.

**Overall: 11/11 pass in production.** No regression found.
