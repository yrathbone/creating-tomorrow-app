# Creating Tomorrow — Current Infrastructure Inventory

**Status:** Read-only audit. No code, configuration, DNS, or infrastructure was
changed to produce this document.

**How this was produced:** every file in the repository was read directly
(not assumed from memory or prior conversation). Live facts about hosting
(response headers, DNS nameservers) were checked directly against the
production site. Every claim below is labeled:

- **VERIFIED** — confirmed by reading the actual file or checking the actual
  live system.
- **INFERRED** — a reasonable conclusion from verified facts, not directly
  stated anywhere.
- **NEEDS VERIFICATION** — could not be confirmed from the repository alone
  (usually because it lives in a provider dashboard you'd need to check).

---

## A. FRONTEND

**Type:** VERIFIED — plain HTML/CSS/JavaScript. No React, no Vue, no other
frontend framework, no build step, no bundler, no `package.json` anywhere in
the repository. `README.md` states this explicitly ("no build step, no
framework — kept deliberately simple"), and the file tree confirms it: every
frontend file is a `.html`, `.js`, or `.css` file served as-is.

**Deployment:** VERIFIED — the frontend is not deployed separately. FastAPI's
`StaticFiles` mount in `backend/main.py` (line 482) serves the entire
`frontend/` folder directly from the same process and the same domain as the
API. There is no separate frontend host, no CDN for static assets beyond
whatever Cloudflare does automatically in front of Render (see Section D).

**Pages** (10 HTML files):

| Page | Purpose |
|---|---|
| `index.html` | Homepage — hero, Guide teaser/modal, "Learn" teasers, final CTA |
| `tool.html` | Tool hub grid **and** the shared UI for Right Fit + Refine (mode-switched by JS) |
| `scratch.html` | Beginning (build a resume from zero) |
| `elevate.html` | Elevate (discovery-interview resume builder) |
| `spotlight.html` | Spotlight (LinkedIn profile review) |
| `prepare.html` | Prepare (interview prep) |
| `learn.html` | Learn hub — links to the 4 articles |
| `article.html` | Renders one article by `?slug=` query param |
| `videos.html` | Video list (all entries currently have `youtube_id: null` — no videos filmed yet) |
| `about.html` | Static About page |

Note: there is **no standalone page for Right Fit or Refine** — both live
inside `tool.html`, switched by a `data-mode` button click (`selectMode()` in
`app.js`). This is a real architectural quirk worth knowing before any
migration: `tool.html` is doing two jobs (hub + two of the six tools).

**Shared JavaScript:**

| FILE | PURPOSE | CALLED BY | CALLS | IMPORTANT FUNCTIONS | SAFE TO MODIFY? | NOTES |
|---|---|---|---|---|---|---|
| `guide.js` | Deterministic navigation helper ("Guide"). A flat lookup table from situation → recommended tool. | `index.html` | Nothing external — no backend call, no LLM | `renderGuideOptions()`, `showGuideRecommendation()`, `openGuide()`/`closeGuide()` | Yes, but changes affect every visitor's first impression of the site | **Guide is not AI.** No LLM call, no `/api/*` request. It's a static `GUIDE_OPTIONS` array. Worth stating plainly since "Guide" sounds like it could be a chatbot. |
| `loading.js` | Shared "processing…" animation/rotating-message helper used by 3 of the 6 tool UIs | `tool.html`, `scratch.html`, `elevate.html` (not `spotlight.html`/`prepare.html` — they define their own inline `PROCESSING_MESSAGES` but still call the shared `startProcessingState`/`stopProcessingState` functions) | Nothing — pure DOM/timer logic | `startProcessingState()`, `stopProcessingState()` | Yes | Explicitly time-based, not real progress — the code comments state this is deliberate (no backend polling exists to report real progress). |
| `markdown.js` | Small hand-written Markdown→HTML converter (headers, bold/italic, links, lists only) | `article.html` | Nothing | `renderMarkdown()`, `inlineMarkdown()` | Yes | Escapes HTML in source text before applying markdown, so it's injection-safe for the article content it's designed for. |

**Per-tool JavaScript (one file per tool, no sharing of tool logic):**

| FILE | PURPOSE | ENDPOINT(S) CALLED | SAFE TO MODIFY? | NOTES |
|---|---|---|---|---|
| `app.js` | Drives **both** Right Fit and Refine inside `tool.html`, switching behavior via a `MODE_CONFIG` object keyed by `"analyze"`/`"refine"` | `/api/analyze`, `/api/refine`, `/api/generate`, `/api/recap` | Yes | All application state (`resumeData`, `reflectiveQuestions`, `lastMatchReport`) lives in plain JS variables — nothing persisted. |
| `scratch.js` | Beginning: one-entry-at-a-time resume builder | `/api/scratch-entry`, `/api/scratch-finalize`, `/api/generate` | Yes | |
| `elevate.js` | Elevate: 3-stage discovery interview | `/api/elevate-start`, `/api/elevate-discover`, `/api/elevate-finalize`, `/api/generate` | Yes | |
| `spotlight.js` | Spotlight: LinkedIn profile review, optional resume upload, sample-profile rendering | `/api/profile-review`, `/api/spotlight-recap` | Yes | Screenshots are held as in-memory `File` objects until submit — never uploaded until the person clicks the review button. |
| `prepare.js` | Prepare: interview prep | `/api/prepare` | Yes | The only tool JS file that escapes model-generated text before inserting it via `innerHTML` (see Security note below). |

**Data files (no logic, just content):**

- `learn-data.js` — article metadata for `learn.html`/`article.html`
- `videos-data.js` — video metadata for `videos.html` (all `youtube_id: null` today)

**Images/assets:** `logo-icon.png`, `guide-mascot.png`, `hero-people.jpg` —
static images, no CMS, no image CDN beyond whatever Cloudflare/Render does
automatically.

**CSS:** one file, `style.css` (2,672 lines). No CSS framework (no
Bootstrap/Tailwind), no preprocessor (no Sass/Less) — hand-written plain CSS.

**External frontend dependency:** VERIFIED — `index.html` loads one Google
Font ("Caveat") from `fonts.googleapis.com`/`fonts.gstatic.com` via a
`<link>` tag. This is the only third-party asset the frontend pulls from
outside Render.

**Frontend security note (VERIFIED, not fixed per this assignment's
instructions):** Most tool-result rendering functions (`app.js`, `scratch.js`,
`elevate.js`) insert text — some of it AI-model output, some of it the
user's own typed input reflected back — into the page using `.innerHTML`
with template literals, without escaping. `spotlight.js` uses `.textContent`
(safe) for its result rendering. `prepare.js` is the only tool script that
defines and uses an `escapeHtml()` helper before using `innerHTML`. This is
a real, currently-live inconsistency, not a hypothetical — flagging it here
because an AWS migration is a natural time to decide whether to standardize
on the safe pattern `prepare.js` already established. No code was changed
for this audit.

---

## B. BACKEND

**Framework:** VERIFIED — FastAPI (`fastapi==0.139.0`), served by
`uvicorn[standard]==0.51.0`. Full dependency list, from
`backend/requirements.txt`:

```
fastapi==0.139.0
uvicorn[standard]==0.51.0
python-multipart      # required by FastAPI to parse file-upload/form requests
python-docx           # generates .docx resume/report files
pypdf                 # extracts text from uploaded PDF resumes
ftfy                  # fixes mis-decoded text ("mojibake") from some PDF exports
anthropic             # official Anthropic Python SDK
pydantic              # FastAPI's request/response validation library
```

No database driver, no ORM, no caching library, no task queue, no cloud SDK
(no `boto3`) is present anywhere in this list or imported anywhere in the
codebase (VERIFIED by search).

**Backend files:**

### `backend/main.py`
- **PURPOSE:** The single FastAPI app. Defines every `/api/*` endpoint,
  validates input, calls the matching tool module, and mounts the static
  frontend.
- **MAIN FUNCTIONS:** one `async def` route handler per endpoint (see the
  endpoint table below), plus a `no_cache_for_frontend` middleware that
  forces `Cache-Control: no-cache` on non-API responses so a deploy never
  leaves stale HTML/JS cached in someone's browser.
- **WHO CALLS IT:** every frontend JS file, via `fetch()`.
- **WHAT IT CALLS:** `extractor.extract_text`, `coach.analyze`,
  `scratch.draft_entry`/`finalize`, `upgrade.upgrade`,
  `elevate.analyze_for_discovery`/`discover`/`finalize_elevate`,
  `profile_review.review_profile`, `prepare.prepare`,
  `resume_builder.build_resume_bytes`/`build_match_recap_bytes`/
  `build_profile_review_recap_bytes`.
- **INPUT:** multipart form uploads (resume files, screenshots, PDFs) and
  JSON bodies, depending on the endpoint.
- **OUTPUT:** JSON (analysis/results) or a `.docx` binary response
  (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`).
- **EXTERNAL SERVICES USED:** none directly — it delegates to the tool
  modules, which call Anthropic.
- **DATA STORED?:** No. Every request is handled and discarded; nothing is
  written to disk or a database (VERIFIED — no file-write, no db-write
  anywhere in this file).
- **ERROR HANDLING:** each route wraps its tool-module call in `try/except`,
  translating a tool-specific error class (e.g. `CoachError`) into a friendly
  `HTTPException(502, ...)`, and any unexpected exception into a generic
  `HTTPException(500, ...)`.
- **SECURITY / PRIVACY:** enforces upload size caps
  (`MAX_UPLOAD_BYTES` = 5 MB, `MAX_IMAGE_BYTES` = 8 MB/screenshot,
  `MAX_TOTAL_IMAGE_BYTES` = 24 MB), a job-description/description length cap
  (`MIN/MAX_JOB_DESCRIPTION_CHARS`), and restricts screenshot uploads to
  `image/png`, `image/jpeg`, `image/webp`. CORS is currently wide open
  (`allow_origins=["*"]`) — harmless today since there's no auth/cookies, but
  worth re-examining if that ever changes.
- **SAFE TO MODIFY?:** Central file — every tool depends on it. High blast
  radius; change with care (not part of this assignment).

### Tool logic modules (one per tool)

| FILE | TOOL | MAIN FUNCTION(S) | RESPONSE STYLE | MAX_TOKENS | RETRY LOGIC | WEB SEARCH |
|---|---|---|---|---|---|---|
| `coach.py` | Right Fit | `analyze()` | Tool-forced structured output (`tool_choice`) | 16000 | Yes, 1 retry | No |
| `upgrade.py` | Refine | `upgrade()` | Tool-forced structured output | 16000 | Yes, 1 retry | No |
| `profile_review.py` | Spotlight | `review_profile()` | Tool-forced structured output | 16000 | Yes, 1 retry | No |
| `scratch.py` | Beginning | `draft_entry()`, `finalize()` | Free-text JSON (`extract_json_object`) | 6000 | No | Yes — `draft_entry()` only, via Anthropic's `web_search_20250305` server-side tool |
| `elevate.py` | Elevate | `analyze_for_discovery()`, `discover()`, `finalize_elevate()` | Free-text JSON | 8000 | No | No |
| `prepare.py` | Prepare | `prepare()` | Free-text JSON | 8000 | No | No |

**Important pattern to understand before migrating anything:** three tools
(Right Fit, Refine, Spotlight) were fixed this year for a reliability bug —
Claude's "extended thinking" could consume the *entire* token budget on some
inputs, leaving zero room for the actual answer and producing an unparseable
response. The fix was switching from asking the model to output raw JSON
text (parsed with regex/brace-hunting in `llm_utils.extract_json_object`) to
Anthropic's own `tool_choice` mechanism, which constrains and validates the
model's output directly. **Three tools still use the older, more fragile
pattern** (Beginning, Elevate, Prepare) and have not hit this bug in
production yet, but are structurally exposed to the same failure mode.
`scratch.py`'s `draft_entry()` is a partial exception: it can't easily use
`tool_choice` forcing because it also needs the model free to call the
`web_search` tool first — this is a real technical constraint, not an
oversight. **This is an observation only — no code was changed.**

### `backend/llm_utils.py`
- **PURPOSE:** Two small shared helpers for the free-text-JSON tools:
  `extract_final_text(response)` (concatenates every text block in a
  response, skipping thinking/tool-use blocks) and
  `extract_json_object(text)` (finds the first `{`...last `}` in a text blob
  and parses it as JSON).
- **WHO CALLS IT:** `scratch.py`, `elevate.py`, `prepare.py`. (`coach.py`,
  `upgrade.py`, `profile_review.py` no longer need it — they use
  `tool_choice` instead.)
- **SAFE TO MODIFY?:** Shared by 3 files — changing it affects all three.

### `backend/extractor.py`
- **PURPOSE:** Converts an uploaded resume/profile file (`.docx`, `.pdf`,
  `.txt`) into plain text, entirely in memory (`io.BytesIO`, no disk write).
- **MAIN FUNCTIONS:** `extract_text(filename, content)` (dispatches by
  extension), `extract_docx_text()`, `extract_pdf_text()`.
- **EXTERNAL SERVICES:** none — `python-docx` and `pypdf` are local libraries.
- **DATA STORED?:** No.
- **NOTES:** Uses `ftfy.fix_text()` to repair a specific real-world PDF
  mojibake bug (UTF-8 dashes/quotes misread as Latin-1).

### `backend/resume_builder.py`
- **PURPOSE:** Builds every downloadable `.docx` file (resumes and recap
  reports) in memory using `python-docx`, matching a fixed visual template.
- **MAIN FUNCTIONS:** `build_resume_bytes()` (main resume — used by
  Beginning, Refine, Right Fit, Elevate), `build_match_recap_bytes()`
  (Right Fit recap), `build_profile_review_recap_bytes()` (Spotlight
  report).
- **DATA STORED?:** No — returns `bytes`, written to disk nowhere.
- **SAFE TO MODIFY?:** Shared by 4 of the 6 tools' download buttons — a
  change here has wide blast radius.

### `backend/prepare.py`, `backend/elevate.py`, `backend/scratch.py`
See the tool-logic table above for their shape. All three follow the same
basic pattern: build a system prompt + user prompt, call
`anthropic.Anthropic().messages.create(...)`, parse the response text as
JSON, raise a tool-specific `*Error` exception on failure. None of them
write anything to disk or a database. All three raise their own exception
class (`ScratchError`, `ElevateError`, `PrepareError`) which `main.py`
converts into an HTTP 502.

---

### FastAPI endpoints (VERIFIED — read directly from `main.py`)

| Endpoint | Method | Frontend caller | Purpose | Input | Python function | External API | Output | Persistence |
|---|---|---|---|---|---|---|---|---|
| `/api/analyze` | POST | `app.js` (mode="analyze") | Right Fit comparison | resume file + job posting text | `coach.analyze()` | Anthropic | JSON | None |
| `/api/recap` | POST | `app.js` | Right Fit downloadable recap | match_report JSON | `resume_builder.build_match_recap_bytes()` | None | .docx | None |
| `/api/refine` | POST | `app.js` (mode="refine") | Refine resume rewrite | resume file | `upgrade.upgrade()` | Anthropic | JSON | None |
| `/api/elevate-start` | POST | `elevate.js` | Elevate stage 1 | resume file | `elevate.analyze_for_discovery()` | Anthropic | JSON | None |
| `/api/elevate-discover` | POST | `elevate.js` | Elevate stage 2 (repeated) | resume_data + Q&A history | `elevate.discover()` | Anthropic | JSON | None |
| `/api/elevate-finalize` | POST | `elevate.js` | Elevate stage 3 | resume_data + confirmed_facts | `elevate.finalize_elevate()` | Anthropic | JSON | None |
| `/api/profile-review` | POST | `spotlight.js` | Spotlight review | screenshots/pasted text/PDF + optional resume | `profile_review.review_profile()` | Anthropic | JSON | None |
| `/api/spotlight-recap` | POST | `spotlight.js` | Spotlight downloadable report | review JSON | `resume_builder.build_profile_review_recap_bytes()` | None | .docx | None |
| `/api/prepare` | POST | `prepare.js` | Interview prep | job description + optional resume | `prepare.prepare()` | Anthropic | JSON | None |
| `/api/scratch-entry` | POST | `scratch.js` | Beginning, per entry | entry_type/title/org/dates/description | `scratch.draft_entry()` | Anthropic (+ web search) | JSON | None |
| `/api/scratch-finalize` | POST | `scratch.js` | Beginning, final step | name/experience/education/skills | `scratch.finalize()` | Anthropic | JSON | None |
| `/api/generate` | POST | `app.js`, `scratch.js`, `elevate.js` | Build final resume .docx | resume_data + ats_mode | `resume_builder.build_resume_bytes()` | None | .docx | None |
| `/api/health` | GET | none (ops/manual check) | Liveness + API-key-configured check | none | inline in `main.py` | None | JSON | None |

**Known limits (VERIFIED, from code):** 5 MB per resume/PDF upload, 8 MB per
screenshot / 24 MB total for Spotlight, 40–15,000 characters for job
descriptions, `MAX_TOKENS` per tool as shown in the table above.

---

## C. SIX CAREER TOOLS — REQUEST FLOWS

### 1. Beginning
```
USER → scratch.html → scratch.js (per-entry form submit)
  → POST /api/scratch-entry → main.api_scratch_entry()
  → scratch.draft_entry() → Claude (+ web_search tool) → free-text JSON parsed by llm_utils
  → JSON response → scratch.js renders drafted bullets + reflective questions
... (repeated per entry) ...
USER clicks "Finish" → scratch.js
  → POST /api/scratch-finalize → main.api_scratch_finalize()
  → scratch.finalize() → Claude → free-text JSON
  → JSON response → scratch.js shows summary + suggested skills
USER clicks "Generate" → scratch.js
  → POST /api/generate → main.api_generate()
  → resume_builder.build_resume_bytes() (no AI call) → .docx bytes
  → browser downloads file
```

### 2. Refine
```
USER → tool.html (mode=refine) → app.js
  → POST /api/refine → main.api_refine()
  → extractor.extract_text() (file → plain text)
  → upgrade.upgrade() → Claude (tool-forced JSON via UPGRADE_TOOL) → validated dict
  → JSON response → app.js renders summary preview + changes/verify lists
USER clicks "Generate" → app.js → POST /api/generate → resume_builder.build_resume_bytes() → .docx download
```

### 3. Right Fit
```
USER → tool.html (mode=analyze) → app.js
  → POST /api/analyze → main.api_analyze()
  → extractor.extract_text()
  → coach.analyze() → Claude (tool-forced JSON via ANALYSIS_TOOL, 1 retry on truncation) → validated dict
  → JSON response → app.js renders match badge/strengths/gaps/flags
USER clicks "Download recap" → app.js → POST /api/recap → resume_builder.build_match_recap_bytes() → .docx download
USER answers reflective questions, clicks "Generate" → app.js → POST /api/generate → .docx download
```

### 4. Elevate
```
USER → elevate.html → elevate.js
  → POST /api/elevate-start → main.api_elevate_start()
  → extractor.extract_text() → elevate.analyze_for_discovery() → Claude → free-text JSON
  → JSON (resume_data, analysis, categories, first questions) → elevate.js shows analysis + Q1
LOOP (repeated 1-3 rounds):
  USER answers a batch → elevate.js
  → POST /api/elevate-discover → main.api_elevate_discover()
  → elevate.discover() → Claude → free-text JSON ({"stage":"questions",...} or {"stage":"confirm",...})
  → elevate.js either shows next batch or the discovered-facts confirmation screen
USER confirms/edits facts → elevate.js
  → POST /api/elevate-finalize → main.api_elevate_finalize()
  → elevate.finalize_elevate() → Claude → free-text JSON (final resume_data + uncovered/changes/verify)
  → elevate.js renders results
USER clicks "Generate" → POST /api/generate → .docx download
```

### 5. Spotlight
```
USER → spotlight.html → spotlight.js
  (attaches: screenshots as File objects, pasted text, PDF, optional resume file)
  → POST /api/profile-review → main.api_profile_review()
  → extractor.extract_text() for PDF/resume; screenshots base64-encoded in place
  → profile_review.review_profile() → Claude (tool-forced JSON via REVIEW_TOOL, multimodal
    content: text blocks + image blocks, 1 retry on truncation) → validated dict
  → JSON response → spotlight.js renders 5 sections + strengths + optional sample profile
USER clicks "Download report" → spotlight.js
  → POST /api/spotlight-recap → resume_builder.build_profile_review_recap_bytes() → .docx download
```

### 6. Prepare
```
USER → prepare.html → prepare.js
  → POST /api/prepare → main.api_prepare()
  → extractor.extract_text() if a resume was attached (optional)
  → prepare.prepare() → Claude → free-text JSON
  → JSON response → prepare.js renders employer priorities, grouped questions
    (with escapeHtml() applied before innerHTML insertion), candidate questions, prep tip
(No .docx download exists for Prepare today — NEEDS VERIFICATION if one was
ever planned; nothing in the code suggests it's missing by accident.)
```

---

## D. EXTERNAL SERVICES

| SERVICE | WHY IT EXISTS | WHAT SENDS DATA TO IT | WHAT DATA IT RECEIVES | WHAT COMES BACK | CONFIG LOCATION | REQUIRED TODAY? | CAN BE REMOVED LATER? | PRIVACY |
|---|---|---|---|---|---|---|---|---|
| **Anthropic API** | Every AI feature in all 6 tools | Every `backend/*.py` tool module | Resume text, job posting text, LinkedIn profile text/screenshots, interview-prep inputs | Structured JSON (resume data, analysis, questions) | `ANTHROPIC_API_KEY` env var (Render dashboard, never in repo); `CT_MODEL` env var, defaults to `claude-sonnet-5` | Yes — the entire product | No — it's the core AI capability | Anthropic's default published data retention applies (documented elsewhere as ~30 days) — **NEEDS VERIFICATION** against Anthropic's current published policy at migration time, since policies can change |
| **GitHub** | Source control + the trigger Render watches for auto-deploy | Developer `git push` | Full source code (no secrets — `.gitignore` excludes `.env`, `*.docx`, `*.pdf`, `test_*`) | N/A | Repo: `yrathbone/creating-tomorrow-app` (VERIFIED via `git remote -v`) | Yes, for the current deploy workflow | Could be replaced by any git host AWS CI/CD reads from (e.g. CodeCommit, or GitHub kept as source-of-truth with AWS reading from it) | No app data ever passes through GitHub |
| **Render** | Hosts the FastAPI app (compute) — builds from `render.yaml`, runs `uvicorn main:app` | N/A (it's the host) | The deployed code + `ANTHROPIC_API_KEY` env var (dashboard-only, never in repo) | Serves the live site | `render.yaml` (build/start commands, `CT_MODEL` value); `ANTHROPIC_API_KEY` set manually in Render's dashboard | Yes — this is the current production host | Yes — this is exactly what an AWS migration would replace | Render sees every request's traffic; no separate data store on Render's side (VERIFIED — no persistence anywhere in the app) |
| **Cloudflare** | Fronts the custom domain — VERIFIED via live response headers (`Server: cloudflare`, `CF-RAY`, `cf-cache-status`) | N/A (sits between the visitor and Render) | All HTTP traffic to `creatingtomorrow.net` | N/A | **NEEDS VERIFICATION** — could not confirm from the repo whether this is a separately-configured Cloudflare account, or simply Render's own edge network (Render is documented to front custom domains through Cloudflare's network automatically). Check the Render dashboard's custom-domain settings, and whether a separate Cloudflare account/dashboard exists, to know which it is. | Not clear it's a distinct account you manage at all — see above | If it's Render's own edge layer, it goes away automatically when Render does; if it's a separate account, it's a DNS-level decision independent of AWS | Cloudflare/Render's edge logging practices — **NEEDS VERIFICATION** |
| **GoDaddy** | DNS for `creatingtomorrow.net` | N/A | DNS queries only | DNS records | Domain registrar/DNS dashboard (outside this repo) — VERIFIED nameservers are `ns63.domaincontrol.com`/`ns64.domaincontrol.com`, GoDaddy's nameserver product | Yes, today | Can coexist indefinitely with any hosting change — DNS and hosting are independent; migrating hosting to AWS does **not** require leaving GoDaddy (this is explicitly one of your stated priorities) | DNS query logging is between GoDaddy and whichever resolver a visitor uses — not something this app controls |
| **Google Fonts** | Loads the "Caveat" font used on the homepage | `index.html` `<link>` tag | Visitor's browser makes a direct request to `fonts.googleapis.com`/`fonts.gstatic.com` | Font file | `index.html` `<head>` | No — purely cosmetic, one font on one page | Yes, trivially (self-host the font file, or drop it) | This is the one third-party request that happens directly from a visitor's browser rather than server-to-server — worth knowing for a strict privacy audit, since it's a (very common, low-risk) third-party request outside your own infrastructure |

**Services checked for and confirmed NOT present (VERIFIED by searching the
whole repo):** no analytics/tracking script of any kind (no Google
Analytics, gtag, Plausible, Segment, Hotjar, Mixpanel), no error-monitoring
SDK (no Sentry), no email service, no SMS service, no payment processor, no
authentication provider, no other AI/search API beside Anthropic (the
"web search" used by Beginning is Anthropic's own server-side `web_search`
tool, not a separate search API/account).

---

## E. CURRENT DATA STORAGE

| Mechanism | Status | Evidence |
|---|---|---|
| PostgreSQL / any database | **NOT USED** | No database driver in `requirements.txt`; no `import` of any db library anywhere in `backend/` (grepped for sqlite/postgres/psycopg/sqlalchemy/redis/boto3/mongo — zero matches) |
| `localStorage` | **NOT USED** | Grepped entire `frontend/` — zero matches |
| `sessionStorage` | **NOT USED** | Same search — zero matches |
| Cookies | **NOT USED** | Same search — zero matches (`document.cookie` — zero matches) |
| Server filesystem writes (resumes, job postings, uploads) | **NOT USED** | Every file read in `extractor.py` goes through `io.BytesIO` in memory; every `.docx` built in `resume_builder.py` returns `bytes` via an in-memory buffer, never `open(..., "w")` to disk. `README.md` and in-code comments state this design choice explicitly and consistently across every tool module. |
| Application logs containing resume/job-posting/PII content | **VERIFIED NOT PRESENT** in the tool modules that were fixed this year (`coach.py`, `upgrade.py`, `profile_review.py`) — their `_diagnose()` functions log only a short category string (e.g. `"truncated_response"`), never the actual text. `scratch.py`, `elevate.py`, `prepare.py` don't log failure diagnostics at all today (they just raise an exception with the raw parse error message, which itself doesn't include the resume/posting text) — **NEEDS VERIFICATION**: confirm Render's own platform-level access/error logs don't capture full request bodies (this is a Render platform behavior question, not something in this repo). |
| Browser URL / query parameters | **VERIFIED, minor use** | `tool.html?mode=refine` / `?mode=analyze` (which tool to show) and `article.html?slug=...` (which article to show) — both are UI-routing only, never resume/job-posting content. |
| Render persistence (disk) | **NOT USED** | Render's free/starter web-service plans have no attached persistent disk by default and this app never tries to write one — consistent with the in-memory design above. |
| Cloudflare logging | **NEEDS VERIFICATION** | Depends on the answer to the Cloudflare open question in Section D — check whatever Cloudflare/Render dashboard actually controls this domain. |
| Browser-tab state (React-style component state, plain JS variables) | **VERIFIED, in-memory only, per tab** | Every tool's frontend JS keeps resume/results data in ordinary JS variables (e.g. `resumeData`, `state.screenshots`) — gone on refresh, never sent anywhere except the one API call that needed it. |

**Bottom line (VERIFIED):** this application currently stores nothing
persistently, anywhere, on the server side. Every request is stateless:
upload → one or more Claude API calls → JSON/file response → discarded.
This is a real, verified architectural property, not just a stated
intention — it directly shapes the AWS recommendation in
`AWS_MIGRATION_PLAN.md` (Section E there addresses whether a database is
needed at all).

---

## Discrepancies found vs. prior assumptions

- `README.md` is **stale**: it describes an early single-tool version of the
  app (mentions `wrenpath.org` as the domain, describes only
  `/api/analyze`/`/api/generate`). The live site is `creatingtomorrow.net`
  with 6 tools and 13 endpoints. Worth updating at some point, but that's a
  documentation fix, not part of this assignment.
- Three tools (Beginning, Elevate, Prepare) still use the older, more
  fragile free-text-JSON response pattern that caused real production
  failures in the other three tools. This wasn't something previously
  documented anywhere — it only became visible by reading every tool
  module side-by-side for this audit.
