# Career Profile / Career Evidence Vault — Architecture Audit

**Read-only audit. No code, database, routes, components, or deployment
settings were changed to produce this document.**

Labeling convention used throughout, per the request:
- **Current State** — verified directly by reading the repository.
- **Recommendation** — a design proposal, not yet built.
- **Not verified from the current codebase** — could not be determined
  from the repo alone; needs your input or a dashboard/provider check.

---

## DECISIONS LOCKED, 2026-09-29

The open questions in Section 23 have been answered. These eight
decisions are now the binding basis for every section below — sections
originally written as open options have been revised to reflect them,
not left as multiple-choice. **Phase 1 has explicitly not started.**
This revision is still audit/design only.

1. **Auth: AWS Cognito**, managed, no custom password handling. Kept
   behind an internal interface so route handlers never touch
   Cognito-specific code directly.
2. **Database: Render-managed PostgreSQL** to start, standard
   Postgres features only, portable migrations. RDS is not provisioned
   as part of this feature.
3. **Frontend: no framework.** Keep the existing plain HTML/JS
   convention for the Career Profile MVP, but organize the new JS into
   focused, reusable modules rather than one large script — the first
   real departure from today's flat, one-file-per-page convention.
4. **Rollout: Career Profile launches as its own authenticated area
   first.** None of the six existing tools are modified in the initial
   build. Sequence: Account → Career Profile → Manual CRUD → Resume
   ingestion → Evidence verification. Right Fit is the first (and only
   initially planned) tool integration, and only after that foundation
   is stable.
5. **No persistent original-file storage for the MVP.** Uploaded resumes
   are processed transiently (extract → structure → discard the original
   bytes) — nothing but the resulting structured/verified data is
   stored. This removes object storage as a launch dependency entirely.
6. **Career Profile is explicitly opt-in**, with clear consent language
   before anything is stored, and eventual review/edit/export/delete
   rights. Existing anonymous tools are unaffected.
7. **Certifications never feed `ExperienceSkill` directly.** A new,
   separate `CertificationSkill` relationship carries certification-
   derived skills, constrained to `learned_exposure` only — it can never
   by itself justify `applied_professionally` or
   `repeated_professional_experience`; only independently verified
   `Experience`/`Achievement` evidence can.
8. Phase 1 has not started. This document is still the design artifact
   under review.

---

## 1. Executive Summary

**A correction to the brief before anything else, stated plainly because
the instructions explicitly ask for verified fact over assumption:** the
background section describes a React frontend and a PostgreSQL database.
**Neither exists in this repository.** Verified by direct inspection
(no `package.json`, no `.jsx`/`.tsx` files anywhere; grepped every backend
file and `requirements.txt` for any database driver — none found):

- **Frontend:** plain HTML/CSS/JavaScript, no framework, no build step,
  10 static pages.
- **Backend:** FastAPI, single `main.py`, 13 endpoints, no router
  modularization.
- **Database:** none. No engine, no ORM, no migrations, no tables,
  nothing persisted anywhere, by design — this has been the site's
  stated privacy position from the start ("we don't save your resume or
  job posting").
- **Authentication:** none. Every request is anonymous and stateless.

This isn't a gap in an otherwise-typical SaaS stack — it's a **genuinely
different starting point** than the brief assumes. The Career Profile
feature is not "add a table to the existing database" — it's the first
persistent, authenticated, multi-user data layer this application has
ever had. That reframes several things:

- The existing six tools' current anonymous, stateless, nothing-saved
  behavior is a **real product promise**, stated in every page's footer.
  Adding accounts must be **opt-in and additive**, not a silent reversal
  of that promise for people who just want to use a tool once.
- There is no existing skill-matching, semantic-matching, or scoring
  **algorithm** anywhere in this codebase. Every tool's "comparison" work
  (Right Fit's match level, Elevate's gap discovery) is done by a single
  LLM call reasoning over raw text, not by any code-level matching logic.
  The Career Match Score / Resume Coverage concept is genuinely new
  engineering, not a refactor of something that already exists.
- The single most relevant existing precedent for this whole feature is
  **Elevate's discovery-interview pattern** (`backend/elevate.py`) —
  propose facts, let the user Accept/Reject/confirm, only add confirmed
  facts to the output. The Career Profile is essentially that pattern
  made persistent and shared across tools instead of thrown away after
  one session. This is a strong, reusable foundation — not a rebuild.
- Existing infrastructure (Render, no separate frontend host) can support
  this feature with **one clearly-needed addition (a database) and one
  clearly-needed new capability (authentication)** — it does not require
  an AWS migration to become technically possible. AWS remains a
  reasonable *later* path, addressed in Section 18, but is not a
  prerequisite.

**Bottom line recommendation:** build the Career Profile as new modules
inside the existing FastAPI app, add a managed PostgreSQL database
(Render's own Postgres add-on is the lowest-friction start — see Section
17), add real authentication (new, from zero), and reuse the Elevate
confirm-facts pattern and the `tool_choice` structured-output pattern
already proven across all six existing tools this year, rather than
inventing new mechanical patterns for the AI-facing parts of this feature.

---

## 2. Current Architecture Map

**Current State**, consistent with `docs/CURRENT_INFRASTRUCTURE.md`
(produced during this session's earlier full audit — that document
remains the authoritative, exhaustive reference; this section
summarizes what's relevant to the Career Profile decision):

```
Visitor's browser
  → Cloudflare (role not fully verified — see Section 11)
  → Render (single web service, single Uvicorn worker)
    → FastAPI (backend/main.py)
      → non-/api/* routes: StaticFiles serves frontend/ directly
      → /api/* routes: dispatch to one of 6 tool modules
        → each tool module calls the Anthropic API directly
  → GitHub (yrathbone/creating-tomorrow-app) — Render auto-deploys on
    push to main
  → GoDaddy — DNS only for creatingtomorrow.net
```

No database anywhere in this picture. No authentication anywhere in this
picture. No separate frontend deployment — one process serves both the
site and the API.

---

## 3. Current Frontend

**Current State:**

- **Structure:** 10 static HTML pages in `frontend/`, each self-contained
  with its own `<script>` tag(s). No `index.js` entry point, no bundler,
  no JSX/TSX anywhere.
- **Routing:** none in the SPA sense — every page is a real, separate
  HTML file the browser navigates to normally (`<a href="...">`). One
  exception: `tool.html` internally switches between "Right Fit" and
  "Refine" modes via JS (`app.js`'s `selectMode()`), driven by a
  `?mode=` query parameter — the closest thing to client-side routing
  in the codebase, and it only covers those two tools.
- **State management:** none, in the React/Redux sense. Each page keeps
  its own plain JS variables (e.g. `state.experience` in `scratch.js`,
  `resumeData` in `app.js`) that exist only for that tab's session and
  are never persisted or shared across pages.
- **Authentication-related components:** none exist.
- **Resume upload flows:** native `<input type="file">` elements, handled
  per-tool by that tool's own JS file, which builds a `FormData` object
  and `fetch()`s it to the matching `/api/...` endpoint. No shared upload
  component — each of `app.js`, `scratch.js` (indirectly, via
  `/api/generate`), `elevate.js`, `spotlight.js`, `prepare.js` implements
  this independently, with near-identical logic each time.
- **Job-description input flows:** plain `<textarea>` elements
  (`tool.html`'s Right Fit mode, `prepare.html`), no shared component.
- **Right Fit interface:** lives inside `tool.html` (mode=`analyze`),
  driven by `app.js`.
- **Refine interface:** also inside `tool.html` (mode=`refine`), same
  file, same JS.
- **Beginning / resume builder interface:** `scratch.html` + `scratch.js`
  — a multi-step wizard (Basics → Experience → Education → Skills →
  Review), the most "form-heavy" existing page, and the closest existing
  precedent for a Career Profile builder's UI complexity.
- **Elevate interface:** `elevate.html` + `elevate.js` — a multi-stage
  wizard with a real Accept/confirm loop (`renderDiscoveredFacts()`,
  discovered facts can be edited or removed before final resume
  generation). This is architecturally the closest existing thing to
  the requested Accept/Reject/Edit verification workflow.
- **Prepare interface:** `prepare.html` + `prepare.js`.
- **LinkedIn-related interface:** `spotlight.html` + `spotlight.js` —
  supports screenshots, pasted text, PDF upload, and (added this
  session) an optional resume upload for additional context.
- **Reusable components:** minimal, and explicitly limited by the
  codebase's own stated convention ("no shared JS between pages" is
  called out in comments as the norm, with `loading.js` as a deliberate,
  named exception). Shared files today: `loading.js` (processing-state
  animation), `markdown.js` (renders the static Learn articles),
  `guide.js` (a hardcoded lookup table, not an AI feature).
- **File-upload components:** none shared — see above.
- **Profile/account components:** **do not exist.** Zero UI anywhere for
  login, registration, or any persistent per-user view.

**Recommendation, stated once here since it recurs through this
document:** the existing "one plain JS file per page, no shared
components, no framework" convention has worked *because* every existing
tool is a single-session, single-purpose wizard. A Career Profile
(persistent CRUD, accept/reject workflows across many entity types, a
dashboard, cross-tool integration) is meaningfully more complex UI than
anything built so far. This is the point in the project's life where
introducing a lightweight frontend framework (or at minimum, a real
shared-component convention) becomes worth the cost it wasn't worth
before — flagged here, not decided; see Section 23.

---

## 4. Current Backend

**Current State:**

- **FastAPI structure:** a single `backend/main.py` (483 lines) defines
  every route directly with `@app.post(...)`/`@app.get(...)` decorators.
  **No `APIRouter` modularization exists** — all 13 endpoints live in one
  file.
- **"Services" layer:** the six tool modules (`coach.py`, `upgrade.py`,
  `scratch.py`, `elevate.py`, `profile_review.py`, `prepare.py`) function
  as a services layer in practice, even though the codebase doesn't use
  that term — each owns its own system prompt(s), request/response
  schema, and Anthropic API call(s).
- **Models/schemas:** no dedicated `models.py`/`schemas.py`. Request
  bodies are validated with inline Pydantic `BaseModel` classes defined
  directly in `main.py` (e.g. `RecapRequest`, `ElevateDiscoverRequest`,
  `GenerateRequest`). Response shapes are plain Python dicts, not
  Pydantic response models — FastAPI serializes them directly.
- **Business logic:** lives inside each tool module's top-level
  function(s) (`analyze()`, `upgrade()`, `draft_entry()`/`finalize()`,
  `analyze_for_discovery()`/`discover()`/`finalize_elevate()`,
  `review_profile()`, `prepare()`). No separate "business logic" layer
  distinct from these — the function *is* the logic.
- **LLM calls:** every tool module calls `anthropic.Anthropic()` directly
  and synchronously. As of this session, **all six tools** use the same
  reliable pattern: a forced tool call (`tool_choice`) against an
  explicit JSON-Schema `input_schema`, a `MAX_TOKENS` budget sized for
  extended thinking, and a single automatic retry on truncation/missing
  fields. (Earlier in this project, three tools used a more fragile
  free-text-JSON pattern; all three were migrated this session after the
  same truncation bug that had already hit Right Fit was found and
  fixed.) Every route handler wraps its tool-module call in
  `run_in_threadpool()` (also added this session) so the synchronous
  Anthropic SDK call doesn't block the single-worker event loop —
  confirmed by testing that concurrent requests now complete in parallel
  rather than serialized.
- **Resume parsing:** `extractor.py` — converts an uploaded `.docx`,
  `.pdf`, or `.txt` file into plain text, entirely in memory
  (`io.BytesIO`, no disk write). This is *text extraction only* — there
  is no structured parsing (no skill extraction, no entity recognition,
  no date parsing) at the code level anywhere. Every tool that needs
  structured resume data (name, roles, bullets) gets it by asking Claude
  to restructure the raw extracted text via its own prompt — this
  restructuring instruction is duplicated, nearly verbatim, across at
  least four tool modules (`coach.py`, `upgrade.py`, `elevate.py`, and
  implicitly `prepare.py`'s handling of an optional resume).
- **Job parsing:** no dedicated module. Job posting text is passed as raw
  string content directly into `coach.py`'s and `prepare.py`'s prompts.
  No code-level extraction of requirements, no keyword list, nothing
  structured — the LLM reads the raw text each time.
- **Resume generation:** `resume_builder.py` — builds `.docx` files with
  `python-docx`, entirely in memory, from a shared `resume_data` schema
  (`name`, `contact`, `headline`, `summary`, `skills`, `experience`,
  `education`, `certifications`, `additional_sections`). This shared
  schema, used by 4 of the 6 tools' download features, is the strongest
  existing "common data shape" precedent in the codebase.
- **Skill matching / job matching / scoring logic:** **does not exist as
  code.** `coach.py`'s `match_level` (`"Low"`/`"Average"`/`"High"`) is
  produced by a single LLM call reasoning qualitatively over the full
  resume and posting text — there is no numeric score, no keyword-overlap
  calculation, no embedding/vector similarity anywhere in this
  repository.
- **File handling:** every upload endpoint enforces a size cap
  (`MAX_UPLOAD_BYTES` = 5 MB for resumes/PDFs; `MAX_IMAGE_BYTES` = 8 MB
  per screenshot / `MAX_TOTAL_IMAGE_BYTES` = 24 MB combined for
  Spotlight) before ever touching the file's contents. As of this
  session, `extractor.py` converts every library-specific parse failure
  (corrupted/fake/empty file) into a friendly `ValueError` rather than
  letting it crash as an unhandled 500 — verified via adversarial testing
  (empty files, fake-extension files, corrupted zip/PDF headers).
- **Authentication / authorization:** **does not exist anywhere in
  `backend/`.** Confirmed by grep across every backend file — no JWT, no
  OAuth, no session middleware, no password handling, no cookie usage.
- **External API integrations:** Anthropic is the only external API any
  backend code calls. `scratch.py`'s `draft_entry()` additionally uses
  Anthropic's own server-side `web_search` tool (not a separate
  third-party search API/account).

---

## 5. Current Database

**Current State: there is no database.**

- **Engine:** none.
- **ORM:** none (no SQLAlchemy, no Tortoise, no Django ORM — nothing).
- **Migration framework:** none (no Alembic).
- **Current models/tables:** none exist.
- **Relationships:** not applicable — nothing to relate.
- **User model:** does not exist.
- **User-scoped data:** does not exist — there are no users to scope data
  to.
- **Where generated resumes/analyses are stored:** nowhere. Every
  response is generated per-request and returned to the browser; nothing
  is written to disk or a database at any point. The browser tab holds
  the data in plain JS variables for that session only.
- **JSON blobs:** JSON is used constantly as the **in-flight interchange
  format** (every API response, every tool's internal `resume_data`
  shape) but **never persisted** — there's no JSONB column anywhere,
  because there's no database column of any kind anywhere.
- **Normalization opportunities:** not applicable to the current
  application; highly applicable to the proposed Career Profile schema —
  see Section 13.

---

## 6. Current Authentication / User Model

**Current State — explicit, not inferred, per the instruction not to
guess:**

| Item | Status |
|---|---|
| Login | Does not exist |
| Registration | Does not exist |
| Sessions | Does not exist |
| JWT | Does not exist |
| OAuth | Does not exist |
| Cookies | Does not exist (verified: zero `document.cookie` usage anywhere in `frontend/`, zero cookie-setting code in `backend/`) |
| Password storage | Does not exist — nothing to store |
| Ownership checks | Does not exist — nothing is owned by anyone |
| Roles / admin | Does not exist |
| Account deletion | Does not exist — nothing to delete |
| Anonymous users | This is the **only** mode the application has. Every visitor, every request, every tool use is fully anonymous and disconnected from every other request, including two requests from the same person five seconds apart. |

There is no partial or legacy auth system to work around or migrate —
this is a completely clean slate.

---

## 7. Current File Storage

**Current State:**

- **Where uploaded files go:** nowhere persistent. Every upload
  (`extractor.py`'s `io.BytesIO`, Spotlight's base64-encoded screenshots
  held in a Python list for the duration of one request) exists only in
  process memory for the lifetime of that single HTTP request, then is
  garbage-collected.
- **Local filesystem vs. database vs. cloud storage:** none of the three
  are used for uploaded content. (Static site assets — `logo-icon.png`,
  `guide-mascot.png`, `hero-people.jpg` — are checked into the git repo
  and served as static files, which is a different thing entirely: fixed
  site assets, not user uploads.)
- **Temporary vs. persistent:** everything is temporary, at the
  single-request scope — there is no "temporary storage that outlives
  the request" tier either (no `/tmp` writes, no session-scoped disk
  cache).
- **Cleanup rules:** none needed, since nothing persists past the
  request.
- **Size limits:** 5 MB (resumes/PDFs), 8 MB per screenshot / 24 MB
  combined (Spotlight) — enforced in `main.py` before the file's bytes
  are ever passed to a parser.
- **Supported formats:** `.docx`, `.pdf`, `.txt` (resumes/profile PDFs);
  `.png`, `.jpg`/`.jpeg`, `.webp` (Spotlight screenshots only).
- **Security risks, current scope:** low, specifically *because* nothing
  is written to disk or served back out — there is no path-traversal
  surface, no public file URL, no stored-file access-control question,
  because there is no stored file. The main risk that did exist (a
  malformed file crashing the parser with a raw 500) was found and fixed
  this session.
- **Would current storage be acceptable for persistent Career
  Profiles? No.** This is the clearest, least-ambiguous "must build new"
  item in this whole audit. A persistent Career Profile requires
  durable, user-owned, access-controlled storage — something between
  "store extracted text/structured data in the new Postgres database"
  and "store the original uploaded file in object storage" (see Section
  12). The current in-memory-only model cannot be extended into this;
  it has to be added alongside it, not evolved from it.

---

## 8. Existing Career-Related Logic We Can Reuse

Per the instruction not to suggest rebuilding what already exists — an
honest, specific split:

### Directly reusable as-is

- **`extractor.py`'s `extract_text()`** — file→plain-text extraction for
  `.docx`/`.pdf`/`.txt`. This is exactly the first step Career Profile
  resume ingestion needs, unchanged.
- **`resume_builder.py`'s `build_resume_bytes()`** and its `resume_data`
  schema (`name`/`contact`/`headline`/`summary`/`skills`/`experience`/
  `education`/`certifications`/`additional_sections`) — the "Build My
  Resume" output step can target this exact, already-proven `.docx`
  template rather than inventing a new one.
- **`llm_utils.py`'s `log_usage()`** and the `tool_choice` +
  single-retry + category-only-diagnostics pattern proven across all six
  tools — the correct mechanical pattern for every new AI call this
  feature needs (skill suggestion, career-archaeology questions,
  evidence-based resume generation), not something to reinvent.
- **`run_in_threadpool()` wrapping pattern** in `main.py` — apply to
  every new blocking AI call from day one, not retrofitted later the way
  it had to be for the existing six tools.

### Reusable as a *pattern*, not as literal shared code today

- **`elevate.py`'s discovery-interview / confirm-facts flow** — this is
  the single strongest precedent in the codebase for the requested
  guided "career archaeology" interview and Accept/Reject/Edit
  verification workflow. `analyze_for_discovery()` → `discover()`
  (repeating, adaptive questions) → `finalize_elevate()` (folds only
  *confirmed* facts in) is structurally almost identical to what the
  Career Profile needs, except Elevate's confirmed facts are thrown away
  after one resume instead of persisted. **Recommendation:** generalize
  this pattern rather than write a new one from scratch.
- **The "restructure raw resume text into JSON" prompt**, currently
  duplicated near-verbatim across `coach.py`, `upgrade.py`, `elevate.py`,
  and (for an optional resume) `prepare.py`/`profile_review.py`. This is
  both an opportunity and a confirmed existing risk (see Section 10) —
  the Career Profile's resume-ingestion step should become the **one**
  place this restructuring happens, with the six existing tools
  eventually calling *it* instead of each re-implementing their own copy
  (see Section 15 for how this could be phased without breaking anything
  today).
- **`coach.py`'s `match_report` schema** (`match_level`, `strengths`,
  `required_qualification_gaps`, `same_word_different_job_flags`,
  `growth_suggestions`) — a reasonable schema *shape* precedent for the
  new Career Match output, though the underlying comparison logic (one
  LLM call over two blobs of text) does not extend to "compare against
  an entire structured, multi-source Career Profile" — that's genuinely
  new work.

### Does not exist — must be built new

- Any skill-extraction, skill-alias, or semantic-matching **code**
  (today this reasoning happens entirely inside a single LLM call's
  judgment, with no structured taxonomy, no embeddings, no exact-vs.
  -semantic distinction represented anywhere).
- Any scoring **algorithm** (today's "match level" is qualitative, not a
  percentage, and not computed — it's generated).
- Any persistent storage, any user model, any provenance/evidence
  data structures, any "evidence level" (Learned/Applied/Professional)
  concept.

---

## 9. Current Deployment / Hosting

**Current State**, consistent with the earlier full infrastructure audit:

- **Frontend hosting:** not separate — served by the same FastAPI
  process via `StaticFiles`.
- **Backend hosting:** Render, free tier, single web service
  (`creating-tomorrow`), single Uvicorn worker (`render.yaml`'s
  `startCommand` has no `--workers` flag).
- **Database hosting:** not applicable — none exists.
- **Domain/DNS:** GoDaddy, nameservers `ns63`/`ns64.domaincontrol.com`.
  `creatingtomorrow.net` A-record → Render's provided IP; `www` CNAME →
  the Render service's `.onrender.com` hostname.
- **Environment variables/secrets:** `ANTHROPIC_API_KEY` and `CT_MODEL`
  set directly in Render's dashboard (`render.yaml` declares the *names*
  only, `sync: false` for the key — the value is never in the repo). No
  Secrets Manager, no Parameter Store, no vault of any kind today.
- **File storage:** none, per Section 7.
- **CI/CD:** Render's own auto-deploy-on-push-to-`main`, nothing more —
  no separate build/test pipeline, no GitHub Actions.
- **GitHub integration:** `yrathbone/creating-tomorrow-app`, connected
  directly to Render's Blueprint sync.
- **Production vs. staging:** **production only.** There is no staging
  or preview environment — every push to `main` deploys directly to the
  live site.
- **Monitoring/logging:** Render's default request logs, plus (added
  this session) category-only token-usage logging (`[usage] tool=...
  input_tokens=... output_tokens=...`) and category-only failure
  diagnostics (`_diagnose()` in each tool module) — never resume/job/
  profile content in any log line, by deliberate design.
- **Cloudflare:** fronts the domain, confirmed via live response headers
  (`Server: cloudflare`, `CF-RAY`) — whether this is a separately
  configured account or simply Render's own edge network remains **Not
  verified from the current codebase**; requires a dashboard check.

---

## 10. Confirmed Risks

Separated exactly as instructed — confirmed vs. likely vs. needs
inspection, all specifically through the lens of "what matters for adding
persistent, authenticated, per-user career data."

### Confirmed (directly verified by reading the code)

1. **No authentication or authorization layer exists anywhere.** Any new
   persistent per-user data model starts with zero existing access
   control to build on — this must be designed and built from scratch,
   not extended from something partial.
2. **CORS is wide open** (`allow_origins=["*"]` in `main.py`). Harmless
   today specifically because there's no auth and no cookies to leak
   cross-origin. **Becomes a real risk the moment authenticated
   sessions/cookies exist** and must be tightened (to the actual
   frontend origin) before any account system ships.
3. **No production build step or component framework in the frontend.**
   Every existing page is hand-written HTML/JS. A Career Profile UI
   (multi-entity CRUD, accept/reject workflows, a dashboard) is a real
   step up in UI complexity from anything built so far under this
   convention.
4. **The "restructure resume into JSON" prompt is duplicated across at
   least four backend modules.** Confirmed by direct comparison of
   `coach.py`, `upgrade.py`, `elevate.py`, and `prepare.py`/
   `profile_review.py`'s resume-handling prompts — a real, existing
   coupling/duplication risk. Adding a fifth copy for the Career Profile
   would compound it rather than resolve it.
5. **The unescaped-`innerHTML` pattern existed** in several frontend
   files (found and partially fixed this session in `app.js`,
   `scratch.js`, `elevate.js`; `prepare.js` already had it right). Any
   new Career Profile frontend code must deliberately follow the
   escaping discipline established this session, not reintroduce the
   older pattern.

### Likely concerns (reasoned from verified facts, not independently proven)

1. **Prompt injection, at higher stakes than today.** Resume/job/LinkedIn
   text is user-supplied and fed directly into LLM prompts across every
   existing tool — today's blast radius is small (no persistence, no
   cross-request effect). A persistent, cross-tool-shared Career Profile
   raises the stakes meaningfully: adversarial or malformed input that
   tricks a model into proposing plausible-but-false "evidence" could,
   if not gated properly, get treated as real going forward. The
   request's own design (AI suggestions are never auto-accepted, always
   require explicit user confirmation) is the correct mitigation — this
   needs to be enforced as a hard architectural rule, not just a UX
   convention that could be bypassed by a future feature shortcut.
2. **No automated verification that the model followed its own
   non-fabrication rules.** Every tool's prompt states strict rules
   (never invent metrics, never invent employers, etc.), and this
   session's manual spot-checking consistently found them followed — but
   that verification was manual, one output at a time. At Career Profile
   scale (many roles × many skills × repeated reuse across tools),
   manual spot-checking does not scale as the only safety net; stronger
   schema constraints and/or provenance requirements (already specified
   in the request) become load-bearing, not optional polish.

### Needs further inspection (cannot be determined from the repo alone)

1. Cloudflare's exact role and account ownership — **Not verified from
   the current codebase.**
2. Whether Render's free tier remains adequate once real authenticated
   session traffic and a database are added — **Not verified from the
   current codebase**; would need real load data once built.
3. Whether any hosting-level rate-limiting exists today — **Not verified
   from the current codebase** either way.

---

## 11. Open Questions / Items You Could Not Verify

- **Cloudflare's role** (Section 9/10) — dashboard check needed.
- **The site's core privacy promise needs an explicit product decision,
  not just a backend one.** Every existing page's footer currently
  states "we don't save your resume or job posting." A persistent
  Career Profile is a genuine reversal of that promise for whoever opts
  in. This needs deliberate, explicit consent UX (clear opt-in, clear
  explanation of what's now being stored and why) — not something that
  can be resolved purely by adding a database and calling it done.
- **Authentication provider preference** — self-built email/password,
  or a managed provider (Cognito, Auth0, Clerk, or similar)? This is a
  real fork with real tradeoffs (control and cost vs. speed and security
  offloading) that only you can decide — see Section 23.
- **Whether a unified login should cover all six existing tools
  immediately, or roll out with the Career Profile as an opt-in addition
  while anonymous one-shot use of the existing tools keeps working
  unchanged.** The request's own framing ("a resume is an output of the
  Career Profile, not the Career Profile itself") suggests the latter —
  worth confirming explicitly before Phase 1.
- **Data retention/export/deletion policy specifics** for Career Profile
  data — the request lists "deletion capability" and "minimal personal
  data collection" as principles; the concrete policy (how long, what
  export format, self-service vs. request-based) isn't yet defined.

---

## 12. Proposed Career Profile Architecture

**Recommendation.** Plugs into the existing app as new modules, not a
rewrite of it:

```
User
  ↓
Frontend (existing static pages UNCHANGED; NEW: a "My Career Profile"
          section — see Section 3's framework-choice flag)
  ↓
Authentication (NEW — does not exist today; see Section 23 for the
                provider-choice question)
  ↓
FastAPI (backend/main.py UNCHANGED entry point; NEW: career_profile
         router(s), likely backend/career/ as a new package rather than
         growing main.py further)
  ↓
Career Profile services (NEW modules, following the existing per-module
                          convention: ingestion, verification/discovery
                          [generalizing elevate.py's pattern], matching,
                          resume generation)
  ↓
PostgreSQL (NEW — Render Postgres add-on to start; see Section 17)
  ↓
Matching / Resume / Interview services
  ↓ ↓
  ↓ → File storage (NEW — object storage for original uploaded files,
  ↓    separate from the structured data in Postgres; see Section 13's
  ↓    ResumeVersion entity)
  → LLM services (Anthropic — SAME client, SAME tool_choice pattern,
                   SAME llm_utils.py helpers already proven this session)
```

**Existing modules reused, not replaced:** `extractor.py`,
`resume_builder.py`, `llm_utils.py`, the `run_in_threadpool()` pattern,
and — as a generalized pattern rather than literal shared code —
`elevate.py`'s confirm-facts flow.

---

## 13. Proposed Preliminary Data Model

**Recommendation — not yet built, no migrations created.** For every
entity: purpose, key fields, relationships, data-source type, whether it
needs provenance, and ownership/security notes.

### `User`
- **Purpose:** the account itself. **Updated per Decision 1:** Cognito
  is the system of record for credentials — this table never stores a
  password of any kind.
- **Key fields:** `id` (internal PK, used by every other table's FK —
  never expose Cognito's own `sub` as a foreign key target, so a future
  provider swap only touches this one table), `cognito_sub` (unique,
  Cognito's own subject identifier — the actual link to the auth
  provider), `email` (cached from Cognito at signup for display/contact
  purposes only — never the auth source of truth, never used to look up
  a user for authorization), `consent_given_at` (nullable timestamp —
  **null means no Career Profile consent yet**, per Decision 6; account
  existence and consent are deliberately separate facts), `created_at`,
  `deleted_at` (soft-delete, to support export-before-delete workflows).
- **Relationships:** one-to-many with every other table below.
- **Data source:** provider-issued (`cognito_sub`, `email` at signup).
- **Provenance:** not applicable — this is the root of ownership.
- **Security:** no credential material stored here at all. The
  `cognito_sub` is the only field that must never be accepted from a
  request body — it's derived exclusively from a verified JWT (see
  Deliverable E).

### `CareerProfile`
- **Purpose:** the top-level container for one user's evidence vault —
  mostly a join point, since most real data lives in the child tables
  below.
- **Key fields:** `id`, `user_id` (FK, unique — one profile per user),
  `created_at`, `updated_at`.
- **Relationships:** one-to-one with `User`; one-to-many with
  `Experience`, `Education`, `Certification`, `Language`,
  `JobPreference`.
- **Data source:** system-generated on account creation.
- **Provenance:** not applicable.
- **Security:** ownership-scoped — every query against this table and
  everything hanging off it must filter by the authenticated user's own
  `user_id`, enforced server-side (never trust a client-supplied
  profile/user ID).

### `Experience`
- **Purpose:** one role (job, or a distinct position within a company).
- **Key fields:** `id`, `career_profile_id` (FK), `title`, `organization`,
  `location`, `start_date`, `end_date` (nullable, for "Present"),
  `description` (free text, user's own words or extracted-and-confirmed),
  `evidence_level` (see below), `source` (`manual` | `resume_upload` |
  `interview`), `source_resume_version_id` (FK, nullable), `verified`
  (boolean), `created_at`.
- **Relationships:** many-to-one to `CareerProfile`; one-to-many with
  `Achievement`, `ExperienceSkill`, `ExperienceTechnology`,
  `GeographicExperience`, `IndustryExperience`.
- **Data source:** mixed — this table is the clearest place the
  user-entered / AI-inferred / verified distinction matters, tracked via
  the `source` and `verified` fields rather than three separate tables.
- **Provenance:** yes — `source` + `source_resume_version_id` trace every
  row back to where it came from.
- **Security:** ownership-scoped via `career_profile_id` → `user_id`.

### `Achievement`
- **Purpose:** a specific, evidenced accomplishment tied to one
  `Experience` — deliberately separate from the role's general
  description so metrics/outcomes can be individually verified and
  individually reused (e.g. in a targeted resume bullet) without
  dragging the whole role description along.
- **Key fields:** `id`, `experience_id` (FK), `text`, `metric_value`
  (nullable — e.g. `"12%"`, `"$20M"`), `verified`, `source`.
- **Relationships:** many-to-one to `Experience`.
- **Provenance:** yes, same pattern as `Experience`.
- **Security:** ownership-scoped via `Experience` → `CareerProfile`.

### `Skill`
- **Purpose:** a canonical skill entry — the normalized "what" (e.g.
  "Risk Management"), independent of any one job or resume.
- **Key fields:** `id`, `name` (unique, canonical form), `category`
  (nullable — e.g. "domain," "technical," "soft skill").
- **Relationships:** many-to-many with `Experience` via
  `ExperienceSkill`; one-to-many with `SkillAlias`.
- **Data source:** system-curated / AI-suggested-then-confirmed.
- **Provenance:** at the `Skill` level, no — provenance belongs on the
  `ExperienceSkill` join row (see below), since the same canonical skill
  can be evidenced by multiple experiences with different confidence.
- **Security:** not user-owned data by itself (a shared taxonomy), but
  writes to it (e.g. adding a brand-new skill name) should still be
  validated/moderated to avoid the taxonomy growing unboundedly from
  free-text noise.

### `SkillAlias`
- **Purpose:** the "Risk & Controls" ↔ "Risk Management" semantic-match
  requirement from the brief — alternate terminology that maps to the
  same canonical `Skill`.
- **Key fields:** `id`, `skill_id` (FK), `alias_text`, `match_type`
  (`exact_synonym` | `semantic_related` — this is where the brief's
  "exact ATS terminology vs. semantic match" distinction actually lives
  in the schema).
- **Relationships:** many-to-one to `Skill`.
- **Data source:** system-curated, likely AI-assisted to build the
  initial taxonomy, human-reviewed before being trusted for exact-term
  substitution in generated resume text (per the brief's own rule: exact
  employer terminology may only be used when verified evidence supports
  it).
- **Provenance:** not applicable — this is shared reference data, not
  per-user evidence.

### `ExperienceSkill` (the one the brief specifically flags)
- **Purpose:** the join between one `Experience` and one `Skill`,
  carrying exactly the "not just that they have it, but where it came
  from and why we believe it" information the brief asks for.
- **Key fields:** `id`, `experience_id` (FK), `skill_id` (FK),
  `source_text` (the actual sentence/phrase that supports this — e.g. a
  quoted resume bullet or interview answer), `evidence_level`
  (`learned_exposure` | `applied_in_project` | `applied_professionally` |
  `repeated_professional_experience` — directly from the brief's
  certifications section, generalized to apply here too), `confidence`
  (`ai_suggested` | `user_confirmed`), `verified_at` (nullable
  timestamp), `verified_by` (nullable — supports a future "someone else
  attested this" case, though self-verification is the only mode needed
  at launch).
- **Relationships:** many-to-one to both `Experience` and `Skill`.
- **Data source:** AI-inferred until `confidence = user_confirmed`.
- **Provenance:** this table *is* the provenance mechanism for the
  whole Skill graph — every other "does this user have skill X" question
  should resolve through this table, never by inferring from `Skill`
  alone.
- **Security:** ownership-scoped via `Experience` → `CareerProfile`.

### `Technology` / `ExperienceTechnology`
- **Purpose:** same pattern as `Skill`/`ExperienceSkill`, specifically
  for named tools/platforms (ERP, TMS, CashPro-style named systems) —
  kept as a separate table rather than folded into `Skill` because named
  technologies behave differently in matching (usually exact-match only,
  rarely semantic) and the brief explicitly calls them out separately.
- **Key fields (`Technology`):** `id`, `name`, `category` (nullable —
  "ERP," "TMS," etc.).
- **Key fields (`ExperienceTechnology`):** same shape as
  `ExperienceSkill` (`source_text`, `evidence_level`, `confidence`,
  `verified_at`).

### `Education`
- **Purpose:** degrees.
- **Key fields:** `id`, `career_profile_id` (FK), `institution`,
  `degree`, `field_of_study`, `graduation_date` (nullable), `source`,
  `verified`.
- **Relationships:** many-to-one to `CareerProfile`.

### `Certification`
- **Purpose:** certifications/training, kept distinct from `Education`
  per the brief's explicit rule that training-derived skills must never
  be represented as professional experience.
- **Key fields:** `id`, `career_profile_id` (FK), `name`, `issuer`,
  `issued_date` (nullable), `expires_date` (nullable), `source`,
  `verified`.
- **Relationships:** many-to-one to `CareerProfile`; one-to-many with
  `CertificationSkill` (below) — **updated per Decision 7:** no longer
  described as feeding `ExperienceSkill`-shaped rows; it has its own
  distinct relationship now, enforced at the schema level, not just by
  convention.

### `CertificationSkill` — new, per Decision 7
- **Purpose:** the certification-derived equivalent of
  `ExperienceSkill`, kept as a **structurally separate table** so a
  certification alone can never be mistaken for — or silently
  contribute evidence toward — professional experience. This is a
  schema-level enforcement of the brief's own rule, not just an
  application-logic convention that could be bypassed by a future
  shortcut.
- **Key fields:** `id`, `certification_id` (FK), `skill_id` (FK),
  `source_text` (why this certification implies this skill — e.g. "IBM
  Product Management Certificate covers customer discovery"),
  `evidence_level` — **constrained by a database CHECK constraint to
  the single value `learned_exposure`.** This is deliberately not left
  to application code to enforce alone: `CertificationSkill.evidence_level
  != 'learned_exposure'` should be a constraint violation, not just a
  bug that's possible to introduce later. `applied_professionally` and
  `repeated_professional_experience` are **not valid values in this
  table at all** — those levels can only ever come from
  `ExperienceSkill`, tied to real `Experience`/`Achievement` evidence.
  Also: `confidence` (`ai_suggested` | `user_confirmed`), `verified_at`.
- **Relationships:** many-to-one to `Certification`; many-to-one to
  `Skill` (the same canonical `Skill` table `ExperienceSkill` uses — a
  skill is one thing regardless of source; only the *evidence* differs).
- **Matching implication, worth stating explicitly since it affects
  Phase 5:** when the Career Match engine scores a job's required
  skills against the profile, a skill supported *only* by
  `CertificationSkill` should be treated as a materially weaker signal
  than one supported by `ExperienceSkill` — likely surfaced as
  "Possible" or "Needs development," never counted the same as
  demonstrated professional evidence in the Career Match percentage.
  The exact weighting is a Phase 5 design detail, not resolved here, but
  the schema-level separation is what makes that distinction possible
  to enforce later at all.
- **Security:** ownership-scoped via `Certification` → `CareerProfile`.

### `Language`
- **Purpose:** spoken/written languages and proficiency.
- **Key fields:** `id`, `career_profile_id` (FK), `name`, `proficiency`
  (free text or an enum — "Professional working proficiency," "Full
  professional proficiency," matching LinkedIn's own categories, since
  Spotlight already ingests LinkedIn-sourced language data in this
  shape).

### `GeographicExperience`
- **Purpose:** international/regional experience, tied to a specific
  `Experience` (per the brief: "did this role involve international
  clients? which countries?").
- **Key fields:** `id`, `experience_id` (FK), `region_or_country`,
  `source_text`, `evidence_level`.
- **Relationships:** many-to-one to `Experience`.

### `IndustryExperience`
- **Purpose:** industries served, same pattern as
  `GeographicExperience`.
- **Key fields:** `id`, `experience_id` (FK), `industry_name`,
  `source_text`, `evidence_level`.

### `JobPreference`
- **Purpose:** the user's own stated preferences (target roles,
  locations, remote/hybrid, comp range if they choose to share it) —
  distinct from evidence, since preferences are never "verified," only
  stated.
- **Key fields:** `id`, `career_profile_id` (FK), `preference_type`,
  `value`.

### `JobAnalysis`
- **Purpose:** one "Do I Match?" run against one job description —
  the persisted record of a Career Match/Resume Coverage calculation.
- **Key fields:** `id`, `career_profile_id` (FK), `job_description_text`,
  `job_title` (nullable, extracted), `career_match_score` (numeric),
  `resume_coverage_score` (numeric, requires a `resume_version_id` to be
  meaningful — coverage is *of* a specific resume), `resume_version_id`
  (FK, nullable), `match_detail` (JSONB — the exact/semantic/partial/
  missing breakdown per qualification; JSONB is the right call *here*
  specifically, since this is a variable-shape, read-mostly, per-analysis
  snapshot, not something that needs relational querying across rows —
  contrast with `ExperienceSkill`, which does need relational querying
  and should stay fully normalized), `created_at`.
- **Relationships:** many-to-one to `CareerProfile`; optionally to
  `ResumeVersion`.

### `ResumeVersion`
- **Purpose:** a generated (or uploaded-and-ingested) resume, versioned
  over time. **Updated per Decision 5: no original file is ever
  persisted.** An uploaded resume is extracted and structured
  transiently (reusing `extractor.py` in memory, exactly as every
  existing tool already does today), and only the resulting structured
  data reaches this table — the original bytes are discarded the moment
  extraction completes, the same in-memory-only lifetime the app's
  existing six tools already guarantee for every upload.
- **Key fields:** `id`, `career_profile_id` (FK), `resume_data` (JSONB —
  matches `resume_builder.py`'s existing schema exactly, so the existing
  `.docx` generator can consume it unchanged), `source`
  (`uploaded` | `generated`), `target_job_analysis_id` (FK, nullable —
  which `JobAnalysis` this version was generated for, if any),
  `created_at`. **No `file_storage_key` field** — removed entirely, not
  left nullable-and-unused, so the schema itself doesn't imply a
  capability the MVP deliberately doesn't have.
- **Relationships:** many-to-one to `CareerProfile`; referenced by
  `JobAnalysis.resume_version_id`.
- **Provenance:** each bullet inside `resume_data` should carry an
  `evidence_ids` array (a list of `Achievement`/`ExperienceSkill` IDs it
  was generated from) — stored inside the JSONB payload itself, since
  this is per-bullet metadata that doesn't need its own relational table
  to be useful, but does need to exist for the brief's provenance
  requirement to actually work end to end.

---

## 14. Proposed User Flow

**Recommendation**, tracing the brief's own example through the schema
above and through both new and existing modules:

1. **User uploads two old resumes.** → New `career_profile` ingestion
   endpoint calls the **existing** `extractor.py` unchanged → raw text →
   a (new, but pattern-reused-from-`elevate.py`) restructuring call
   using the `tool_choice` pattern, producing candidate `Experience`,
   `Achievement`, `ExperienceSkill` (etc.) rows with `confidence =
   ai_suggested`, `verified = false`.
2. **System asks user to verify.** → Frontend renders the candidates
   (generalized version of Elevate's `renderDiscoveredFacts()`
   accept/reject/edit UI). Each accept flips that row's `verified` to
   `true` and `confidence` to `user_confirmed`. Nothing becomes real
   evidence until this step.
3. **User adds IBM Product Management certification.** → New
   `Certification` row, `source = manual`. → System suggests likely
   `ExperienceSkill`-style rows tied to it at `evidence_level =
   learned_exposure` only (per the brief's explicit rule) — again
   `ai_suggested`, again requiring confirmation.
4. **User confirms some, rejects others.** → Same accept/reject
   mechanism as step 2, reused, not reinvented.
5. **User enters a target job.** → New `JobAnalysis` row created;
   `job_description_text` stored. A new matching service queries every
   `verified = true` `ExperienceSkill`/`ExperienceTechnology` row (plus
   `SkillAlias` for semantic matching) across the *entire* Career
   Profile — not just one resume — and produces the exact/semantic/
   partial/missing breakdown, weighted by required vs. preferred
   qualifications, stored in `match_detail`.
6. **System displays Career Match (88%) and Resume Coverage (61%).** →
   Resume Coverage specifically requires comparing `match_detail` against
   whichever `ResumeVersion.resume_data` is currently "current" — a
   second, smaller comparison pass, not the same calculation reused.
7. **User selects Build My Resume.** → A new resume-generation service
   queries the verified evidence ranked against this specific
   `JobAnalysis`, calls the **existing** `resume_builder.py` (unchanged)
   with a `resume_data` payload assembled from real, verified rows only,
   writes a new `ResumeVersion` row (with per-bullet `evidence_ids`),
   and returns the `.docx` exactly as today's `/api/generate` already
   does.

---

## 15. Integration With Existing Creating Tomorrow Tools

**Recommendation.** The key design goal: **every existing tool keeps
working exactly as it does today for anonymous users** — the Career
Profile is additive, not a breaking change to current behavior.

- **Right Fit (`coach.py`):** if a logged-in user has a Career Profile,
  offer "compare against your full Career Profile" as an option
  alongside today's "paste one resume" flow. Under the hood, this means
  `coach.analyze()` gaining an optional path that receives
  Career-Profile-derived evidence instead of (or alongside) raw resume
  text — the function's core prompt logic doesn't need to change, only
  what feeds it.
- **Refine (`upgrade.py`):** similarly, could optionally pull from the
  Career Profile's verified evidence instead of one uploaded file — but
  Refine's whole identity is "polish what's already on this one resume,
  don't add anything" (its inference tolerance is deliberately the
  *lowest* of any tool), so this integration is lower-priority and lower
  -value than Right Fit's or the new Build-My-Resume flow.
- **Beginning (`scratch.py`):** a natural **feeder** into the Career
  Profile — someone building their first resume from zero is, in effect,
  building their first Career Profile entries too. Long-term, Beginning
  could write directly into `Experience`/`Achievement` rows instead of
  (or in addition to) generating a one-off `.docx`.
- **Elevate (`elevate.py`):** the deepest integration opportunity.
  Elevate's whole discovery-interview mechanism is the prototype for the
  Career Profile's verification workflow — long-term, Elevate's
  discovered facts should write into the Career Profile directly instead
  of only feeding one resume that's then discarded.
- **Prepare (`prepare.py`):** could read Career Profile evidence instead
  of requiring a fresh resume upload each time, for the "resume-based
  questions" group specifically.
- **Spotlight (`profile_review.py`):** already accepts an optional
  resume for additional context (built this session) — a logged-in
  user's Career Profile is a strictly richer version of that same input,
  a natural drop-in replacement for the optional-resume parameter.

None of this requires changing any of the six tools' existing anonymous,
no-account entry points — every integration above is framed as an
*additional* path available only to logged-in users with a Career
Profile.

---

## 16. Phased Implementation Plan

**Recommendation**, adjusted from the brief's example structure based on
what this specific codebase actually needs first.

### Phase 0 — Architecture cleanup / prerequisites
- **Objectives:** tighten CORS to the real frontend origin (not `*`);
  decide and stand up the authentication approach (Section 23); decide
  the database provider (Section 17); extract the duplicated
  "restructure resume into JSON" prompt logic into one shared function
  the existing tools can optionally adopt later, without changing their
  current behavior yet.
- **Files likely affected:** `backend/main.py` (CORS config), a new
  shared module for the extraction prompt.
- **DB changes:** none yet — provisioning only.
- **API changes:** none yet.
- **Frontend changes:** none yet.
- **Dependencies:** a real decision on the auth provider question
  (Section 23) blocks everything after this phase.
- **Risks:** low if scoped exactly as above; the temptation to also
  "clean up" the six existing tools at the same time should be resisted
  — keep this phase narrow.
- **Complexity:** Low.

### Phase 1 — Accounts / authentication
- **Objectives:** Cognito-backed login/registration/session handling
  (Decision 1, locked) — the single biggest net-new capability this
  whole feature depends on. **Explicitly not started** — this remains
  planning only per your instruction.
- **Files likely affected:** new `backend/auth/` package (see
  Deliverable G for exact contents); `main.py` gains auth dependency
  injection for protected routes only — the 13 existing anonymous
  endpoints are untouched.
- **DB changes:** `User` table only — Cognito itself holds credentials,
  so there's no password/session-token table on our side.
- **API changes:** no custom `/api/auth/*` login endpoints — Cognito's
  own API handles signup/login directly from the frontend; the backend
  only ever verifies tokens (see Deliverable C).
- **Frontend changes:** new login/register pages, styled consistently
  with the existing site (Deliverable C) rather than Cognito's default
  Hosted UI look.
- **Dependencies:** none remaining — Decision 1 resolved the only open
  question this phase had.
- **Risks:** still the highest-stakes phase, now for token/session
  handling and CORS tightening specifically (credential storage itself
  is Cognito's problem, not ours, which meaningfully lowers this phase's
  risk versus the self-built option originally considered).
- **Complexity:** Medium (lower than originally estimated, specifically
  because Decision 1 removed the self-built-auth path).

### Phase 2 — Career Profile CRUD
- **Objectives:** `CareerProfile`, `Experience`, `Education`,
  `Certification`, `Language` tables and basic manual-entry CRUD
  endpoints/UI — no AI involvement yet, just "can a logged-in user type
  in and edit their own career facts."
- **Files likely affected:** new `backend/career/` package; new
  `frontend/career-profile.html` + JS.
- **DB changes:** the core tables from Section 13 (excluding the
  skill/evidence graph for now).
- **API changes:** new `/api/career/*` CRUD endpoints.
- **Frontend changes:** the first real multi-entity form UI in the
  codebase.
- **Dependencies:** Phase 1.
- **Risks:** ownership-scoping bugs (a query that forgets to filter by
  the authenticated user) are the main risk class here — worth explicit,
  deliberate test coverage from the start, not an afterthought.
- **Complexity:** Medium.

### Phase 3 — Resume ingestion → candidate evidence
- **Objectives:** upload a resume, extract it (`extractor.py`, reused
  unchanged), restructure it (the shared extraction logic from Phase 0),
  and write candidate rows with `confidence = ai_suggested,
  verified = false`.
- **Files likely affected:** new ingestion service; `Skill`,
  `SkillAlias`, `Technology`, `ExperienceSkill`,
  `ExperienceTechnology` tables now come into play.
- **DB changes:** the skill/evidence-graph tables from Section 13.
- **Dependencies:** Phase 2.
- **Risks:** this is where prompt-injection stakes rise (Section 10) —
  candidate rows must never be created as already-verified, no matter
  what the input text says.
- **Complexity:** Medium.

### Phase 4 — User verification workflow
- **Objectives:** the Accept/Reject/Edit UI, generalized from
  `elevate.js`'s existing `renderDiscoveredFacts()` pattern.
- **Files likely affected:** new frontend component (or page section);
  new `/api/career/evidence/{id}/confirm|reject` endpoints.
- **Dependencies:** Phase 3.
- **Risks:** low, technically — the pattern already exists and works;
  the work here is generalizing it, not inventing it.
- **Complexity:** Low-Medium.

### Phase 5 — Job analysis / Career Match
- **Objectives:** the exact/semantic/partial/missing comparison engine
  and the Career Match Score calculation, weighted by required vs.
  preferred qualifications.
- **Files likely affected:** new matching service; `JobAnalysis` table.
- **Dependencies:** Phase 3 (needs a populated, verified evidence graph
  to compare against — even a thin one).
- **Risks:** this is the phase with the most genuinely new algorithmic
  work in the whole plan (Section 8 confirmed nothing like this exists
  today) — budget real design/iteration time, not just build time.
- **Complexity:** High.

### Phase 6 — Resume Coverage
- **Objectives:** the second metric — how much of the *matched*
  qualifications a specific `ResumeVersion` actually communicates.
- **Dependencies:** Phase 5 and at least one `ResumeVersion` to compare
  against.
- **Complexity:** Medium (smaller than Phase 5, reuses its output).

### Phase 7 — Evidence-based resume generation
- **Objectives:** "Build My Resume" — query ranked verified evidence,
  call `resume_builder.py` (reused unchanged) with an assembled
  `resume_data` payload, attach per-bullet `evidence_ids`.
- **Dependencies:** Phase 5 (needs a `JobAnalysis` to target).
- **Complexity:** Medium-High (the provenance-linking requirement is the
  hard part, not the resume generation itself, which reuses existing
  code).

### Phase 8 — Version history
- **Objectives:** list/compare/restore past `ResumeVersion` rows.
- **Complexity:** Low.

### Phase 9 — Integration into existing tools
- **Objectives, locked per Decision 4:** Right Fit only, and only after
  Phases 1-4 are stable in production. No other tool is touched in the
  initial build — Refine, Beginning, Prepare, and Spotlight integrations
  (Section 15) remain future work, not part of this plan's scope.
- **Complexity:** Medium, for the one integration actually planned.

### Phase 10 — Future job search / recommendations
- **Objectives:** explicitly out of scope for detailed planning here —
  the brief itself frames this as a future direction, not a near-term
  phase.
- **Complexity:** Not yet scoped.

---

## 17. Hosting Recommendation

**Recommendation, updated for the locked decisions above:**

### Keep Now
- **Render** for backend hosting — nothing about this feature requires
  leaving it. Render's own **managed PostgreSQL add-on** is the decided
  database (Decision 2).
- **GoDaddy** for DNS — unaffected by any of this.
- **The current no-separate-frontend-host model** — decided to stay
  (Decision 3); the Career Profile pages are served by the same FastAPI
  process, same as every page today.

### Short-term (needed specifically for Career Profiles)
- **Render's managed PostgreSQL add-on** (Decision 2 — locked, not a
  choice between options anymore).
- **AWS Cognito** (Decision 1 — locked). Worth naming plainly: this is
  the one piece of AWS actually entering the architecture now, not
  later — a deliberate, narrowly-scoped adoption of one managed service
  for one specific job (authentication), not the start of a broader
  migration. Everything else — compute, database — stays on Render.
  Section 18 still applies: this is compatibility-driven adoption of the
  right tool for one job, not migration for its own sake.
- **Object storage is explicitly NOT a launch dependency** (Decision 5
  — this removes what was previously the one short-term item without an
  obvious "stay on Render" answer). Uploaded resumes are processed
  transiently and discarded; nothing needs a place to live beyond the
  request that ingests it.
- **A staging/preview environment**, which doesn't exist today — still
  worth having before shipping authentication and real user data,
  unchanged from the original recommendation.

### Consider Later
- **S3**, only if persistent original-file storage is ever built as its
  own later feature (Decision 5 explicitly defers this, not cancels it).
- **CloudFront/S3 for the frontend**, only if the no-framework decision
  (Decision 3) is ever revisited.
- **Secrets Manager or Parameter Store**, once there's more than the
  current API key plus a database connection string plus Cognito
  configuration to manage — worth re-evaluating once Phase 1 is actually
  built, not before.
- **Moving the database to RDS**, only if/when Render Postgres's own
  limits become a real, observed constraint — not preemptively (Decision
  2, explicit).

---

## 18. AWS Migration Compatibility

**Recommendation — explicitly not a "migrate now" recommendation,** per
your own instruction not to conflate feature development with cloud
migration absent a technical dependency. None exists here. This section
maps *compatibility*, not urgency.

| AWS Service | Would it make sense here? | Why / why not |
|---|---|---|
| **Cognito** | **Decided: yes (Decision 1).** | Solves Phase 1's hardest problem (secure credential/session handling) without building it yourself, kept behind an internal interface (Deliverable E) so this choice stays swappable later if it ever needs to be |
| **RDS PostgreSQL** | Not now (Decision 2, explicit) | Render Postgres and RDS Postgres are the same engine — the schema in Section 13 is fully portable either direction with zero redesign whenever the move actually makes sense |
| **S3** | Not a launch dependency (Decision 5) | Deferred, not cancelled — only relevant if persistent original-file storage is ever built as a separate later feature |
| **App Runner / ECS / Lambda** | Not for this feature specifically | Nothing about Career Profiles requires moving backend compute off Render — this would be the same AWS backend-hosting decision already covered in `AWS_MIGRATION_PLAN.md`, independent of this feature |
| **CloudFront / Amplify** | Only if the frontend framework question resolves toward a real build step | Otherwise no different from today's Render-served static files |
| **Secrets Manager** | Later, once there's more than one secret to manage | Not urgent at today's scale (one API key) |
| **CloudWatch** | Automatic if any AWS compute service is ever adopted | Not a reason to adopt one by itself |

**Architecture decisions worth making now specifically to avoid a
painful AWS migration later, even while staying on Render today:**
- Use standard PostgreSQL (not a Render-proprietary extension) — already
  the plan, since Render Postgres *is* standard Postgres.
- Keep the authentication layer behind a clean interface (verify a
  token/session → get a user ID) rather than deeply coupling route
  handlers to one specific provider's SDK — makes a later Cognito swap
  (or the reverse) much cheaper.
- Treat object storage (if adopted) as a plain key-based interface
  (`file_storage_key` in `ResumeVersion`, per Section 13) rather than
  hardcoding provider-specific URLs anywhere in application logic.

---

## 19. Files / Modules Likely To Be Reused

- `backend/extractor.py` — unchanged.
- `backend/resume_builder.py` — unchanged, targeted by the new
  resume-generation service.
- `backend/llm_utils.py` — unchanged, its `log_usage()` and the
  `tool_choice` pattern it supports are the template for every new AI
  call.
- The `run_in_threadpool()` wrapping convention from `backend/main.py`.
- `elevate.py`'s discovery/confirm-facts flow — reused as a *pattern* to
  generalize, not as literal imported code.
- `coach.py`'s `match_report` schema — reused as a *shape* precedent.

## 20. Files / Modules Likely To Need Modification

- `backend/main.py` — CORS tightening (Phase 0); eventually gains
  auth-dependency wiring for any new protected routes (Phase 1+), though
  the existing 13 anonymous endpoints should need no behavioral changes.
- `coach.py`, `upgrade.py`, `elevate.py`, `prepare.py`,
  `profile_review.py` — each gains an *optional* new code path for
  reading Career-Profile-sourced evidence (Phase 9), with their current
  anonymous-input behavior fully preserved.
- `render.yaml` — adds a database connection string env var reference
  once Postgres is provisioned.

## 21. New Modules Likely Needed

- `backend/auth/` — authentication/session/token handling.
- `backend/career/` — Career Profile CRUD, ingestion, verification,
  matching, and resume-generation services (likely several files inside
  this package, following the existing one-module-per-concern
  convention).
- `backend/db.py` or similar — the first database connection/session
  management this codebase will have.
- A migrations directory (Alembic, if using SQLAlchemy — a real
  framework choice, not decided by this audit).
- `frontend/career-profile.html` + a new JS file (or several, following
  the existing per-page convention) — or, if the frontend-framework
  question resolves toward adopting one, a proper component structure
  instead.
- `frontend/login.html` / `frontend/register.html` (or equivalent, if a
  managed auth provider's own hosted UI is used instead).

---

## 22. Recommended Next Step

Resolve the two blocking decisions in Section 23 (auth provider,
database provider) — everything in Phase 0 onward depends on both, and
neither can be inferred from the codebase; they're genuinely yours to
make. Once decided, Phase 0 (CORS tightening + shared extraction-prompt
refactor + infrastructure provisioning) is small, low-risk, and doesn't
touch any existing user-facing behavior — a reasonable place to actually
start building, once you've reviewed and approved this audit.

---

## 23. Questions For Us Before Any Coding Begins

**Resolved 2026-09-29 — see "DECISIONS LOCKED" near the top of this
document.** The six questions originally posed here (auth provider,
database provider, frontend approach, rollout scope, original-file
retention, privacy/consent posture) were all answered and are now
binding decisions 1-6. This section is kept, unedited in spirit, as the
historical record of what was asked — not because it's still open.

**Remaining open items, surfaced while producing Deliverables A-G below
— none of these block Phase 0, but worth your input before Phase 1:**

1. **Cognito Hosted UI vs. a custom-built login page calling Cognito's
   API directly.** Deliverable C recommends the custom-page approach (to
   match the site's existing visual design, consistent with Decision 3's
   "no framework, but still our own pages" spirit) — flagged as a
   recommendation, not treated as already decided by Decision 1, since
   Decision 1 addressed *which provider*, not *which login UI pattern*.
2. **SQLAlchemy + Alembic as the ORM/migration tooling** — proposed in
   Deliverable B as the natural pairing for "standard PostgreSQL,
   portable migrations" (Decision 2), but this specific tool choice
   wasn't explicitly named in your decisions, so it's presented as a
   recommendation to confirm, not an eighth locked decision.
3. **Certification-derived skill matching weight** (referenced in the
   updated `CertificationSkill` entity, Section 13) — the schema now
   enforces that certifications can never claim professional-level
   evidence, but the exact scoring weight a certification-only skill
   should carry in the Phase 5 Career Match percentage is a real design
   decision for that phase, not resolved here.

---

## 24. Deliverable A — Data Model Update Summary

Full detail is in the revised Section 13 above; this is a short index of
what actually changed, so the diff from the original proposal is easy to
scan without re-reading every entity:

- **`User`:** `password_hash` removed entirely; added `cognito_sub`
  (the real identity link) and `consent_given_at` (Decision 6 — null
  until explicit consent).
- **`ResumeVersion`:** `file_storage_key` removed entirely (Decision 5)
  — no field even exists to imply the capability.
- **`Certification`:** its relationship to skill evidence was
  restructured — no longer implied to feed `ExperienceSkill`-shaped
  rows.
- **`CertificationSkill`:** new table (Decision 7) — structurally
  separate from `ExperienceSkill`, with `evidence_level` constrained by
  a database CHECK constraint to `learned_exposure` only.
- **Everything else** (`CareerProfile`, `Experience`, `Achievement`,
  `Skill`, `SkillAlias`, `ExperienceSkill`, `Technology`/
  `ExperienceTechnology`, `Education`, `Language`,
  `GeographicExperience`, `IndustryExperience`, `JobPreference`,
  `JobAnalysis`) is **unchanged** from the original proposal —
  `ExperienceSkill` specifically was kept exactly as proposed, per
  Decision 7's explicit instruction.

---

## 25. Deliverable B — Phase 0 Exact Implementation Checklist

**Recommendation.** Ordered, concrete, still zero production code —
this is provisioning and one code-organization refactor, not feature
work. Each item names what it actually is, not just a label.

1. **Tighten CORS in `backend/main.py`** — replace
   `allow_origins=["*"]` with the real frontend origin(s)
   (`https://creatingtomorrow.net`, plus whatever local dev origin is
   used). Harmless today with no auth/cookies; becomes load-bearing the
   moment Phase 1 introduces authenticated requests, so doing it now
   means Phase 1 doesn't inherit a half-finished security prerequisite.
2. **Create the Cognito User Pool** (AWS Console or IaC — a one-time
   setup task, addressed in full in Deliverable C). No application code
   depends on this existing yet in Phase 0; this just makes the User
   Pool ID/Client ID available for Phase 1.
3. **Provision the Render PostgreSQL add-on** (full configuration in
   Deliverable D) and confirm `DATABASE_URL` is available as an
   environment variable to the existing web service — nothing reads it
   yet.
4. **Choose and pin the ORM/migration tooling** — recommended:
   SQLAlchemy (2.x, using its modern declarative style) + Alembic.
   Rationale: this is the most standard, most portable pairing for
   "plain PostgreSQL, no proprietary features, migrations that move
   cleanly to RDS later" (Decision 2) — nothing exotic, nothing that
   locks you to Render. Add both to `backend/requirements.txt`; do not
   create any models or migrations yet.
5. **Add the remaining new dependencies to `backend/requirements.txt`:**
   a Postgres driver (`psycopg[binary]` — the modern, actively
   maintained psycopg3, rather than the older psycopg2), and a JWT
   verification library for Cognito tokens (`python-jose[cryptography]`
   is the common choice for verifying Cognito's RS256-signed JWTs
   against its published JWKS).
6. **Extract the duplicated "restructure resume into JSON" prompt logic**
   (confirmed duplicated across `coach.py`, `upgrade.py`, `elevate.py`,
   and `prepare.py`/`profile_review.py` in Section 8) into one new shared
   function — e.g. `backend/resume_ingestion.py`. **Critically: do not
   change what any of the six existing tools do yet.** This step is
   purely "create the shared version," not "make the existing tools use
   it" — that migration is separate, later work, and out of scope for
   Phase 0. The immediate purpose is that Phase 3 (resume ingestion into
   the Career Profile) has one correct place to call, not a sixth
   near-duplicate copy.
7. **Do not touch:** any existing route in `main.py` beyond the CORS
   line in step 1; any existing tool module's behavior; `render.yaml`'s
   existing `buildCommand`/`startCommand` (only its environment variable
   references grow, in step 3).
8. **Verify, before calling Phase 0 done:** the existing six tools still
   work exactly as before (a quick pass through each, matching this
   project's established practice of verifying against the real app, not
   just reading the diff) — Phase 0 should be invisible to every current
   anonymous user.

---

## 26. Deliverable C — Proposed Cognito Integration Design

**Recommendation.**

### Pool setup
- One Cognito **User Pool** for this application. Standard attributes:
  email (required, used as the username), no phone number requirement
  (keep the signup form minimal, consistent with Decision 6's "minimal
  personal data collection" principle).
- **Email/password sign-in only for the MVP** — no social login (Google/
  Microsoft OAuth via Cognito) in the initial build; a reasonable later
  addition, not a Phase 1 requirement.
- MFA: optional, not required, for the MVP — worth revisiting once real
  users exist, but not a launch blocker for what is, at this stage, a
  career-document storage feature, not a financial one.

### Login UI: custom page, not Cognito's Hosted UI
- **Recommendation:** build `frontend/career/login.html` /
  `register.html` as plain HTML/JS (consistent with Decision 3), calling
  Cognito's own API directly via the `amazon-cognito-identity-js` SDK
  (a client-side library, not a backend dependency) rather than
  redirecting to Cognito's default-styled Hosted UI.
- **Why:** Cognito's Hosted UI is faster to stand up but visually
  breaks from the rest of the site (it's AWS's own default styling,
  not this site's cobalt/gold brand) — for a feature meant to feel like
  a natural part of Creating Tomorrow rather than a hand-off to a
  third-party screen, the small extra effort of a custom page is worth
  it. This is presented as a recommendation (Section 23, item 1), not
  something Decision 1 already settled.

### Token flow
1. User submits email/password on the custom login page →
   `amazon-cognito-identity-js` calls Cognito directly from the
   browser — the backend is never involved in this exchange, and never
   sees the password.
2. Cognito returns an **ID token** (a signed JWT containing the user's
   `sub`, email, and standard claims) and an access token.
3. The frontend stores the ID token in memory for the session (a plain
   JS variable, matching this app's existing "nothing persists across a
   reload" convention) — **not `localStorage`**, to limit the token's
   exposure window if the page is ever compromised by any future
   XSS-class issue; re-authenticating on a hard refresh is an acceptable
   MVP tradeoff for the added safety.
4. Every subsequent request to a protected `/api/career/*` endpoint
   includes the ID token as `Authorization: Bearer <token>`.

### Backend verification (the "internal interface" from Decision 1)
- A single new FastAPI dependency, e.g. `get_current_user()` in
  `backend/auth/dependencies.py`:
  1. Extracts the bearer token from the request.
  2. Verifies its signature against Cognito's published JWKS (fetched
     from Cognito's well-known endpoint, cached rather than fetched on
     every request).
  3. Confirms the token isn't expired and its issuer/audience match this
     app's User Pool/Client ID.
  4. Looks up (or, on a verified user's very first request, creates)
     the internal `User` row by `cognito_sub`.
  5. Returns the internal `User` object — **every route handler
     downstream only ever sees this internal object, never a raw Cognito
     token or claim.** This is the entire "internal interface" Decision 1
     asked for: if the auth provider ever changed, only this one
     dependency's implementation would need to change — no route handler
     anywhere would need to know or care.

---

## 27. Deliverable D — Proposed Render PostgreSQL Configuration

**Recommendation.**

- **Plan tier:** start on Render's lowest-cost Postgres tier available.
  Consistent with this project's established budget-consciousness (the
  same reasoning that drove the Lambda-over-ECS decision earlier this
  project) — upgrade only once real usage data shows it's actually
  needed, not preemptively.
- **SSL:** Render Postgres requires SSL connections by default
  (`sslmode=require` in the connection string) — this needs to be
  reflected in however the SQLAlchemy engine is configured in Phase 0/1,
  not discovered as a surprise later.
- **Connection wiring:** link the Postgres instance to the existing
  `creating-tomorrow` web service in Render's dashboard, which
  auto-populates a `DATABASE_URL` environment variable — no manual
  connection-string copying into `render.yaml`, consistent with how
  `ANTHROPIC_API_KEY` is already handled (dashboard-set, never in the
  repo).
- **Connection pooling:** a single low-tier Postgres instance has a
  real, limited maximum connection count. Configure SQLAlchemy's engine
  with a conservative pool size (small `pool_size`, modest `max_overflow`)
  from the start, rather than defaulting to values sized for a much
  larger deployment — this matters more than it would on a bigger plan,
  specifically because of the deliberately low-cost tier choice above.
- **Backups/retention:** Render's exact backup retention policy at each
  plan tier — **Not verified from the current codebase**; check Render's
  current published Postgres documentation/dashboard before relying on
  any specific retention window, since this materially affects the
  Decision 6 "users must eventually be able to export/delete" commitment
  (a backup retention window is a real recovery/privacy consideration,
  not just an operational detail).
- **Migrations:** Alembic (Deliverable B), run manually for now — Render
  supports a "Pre-Deploy Command" that could run `alembic upgrade head`
  automatically on future deploys, worth adopting once the migration
  history is established, not on day one while the schema is still
  actively taking shape.

---

## 28. Deliverable E — Ownership / Authorization Pattern for Career Profile Routes

**Recommendation.**

**The core rule, stated once so it can be enforced consistently: every
Career Profile route derives the acting user exclusively from the
verified Cognito token (via `get_current_user()`, Deliverable C) — never
from a path parameter, query string, or request body.** A URL like
`/api/career/experiences/42` must never trust a client-supplied user or
profile ID to decide *whose* data row 42 belongs to; ownership is always
re-derived server-side from the token on every single request.

Concretely:

1. **Every protected route declares `current_user: User =
   Depends(get_current_user)`** as a parameter — FastAPI's dependency
   injection makes this hard to accidentally omit, since the route
   simply doesn't have a `current_user` to use if the dependency isn't
   declared.
2. **A single helper, not repeated per-route logic:**
   `get_career_profile_or_404(db, current_user)` — looks up the
   `CareerProfile` row belonging to `current_user.id`, raising 404 if
   none exists (e.g. consent hasn't been given yet — see Deliverable F).
   Every route that touches Career Profile data calls this helper first,
   rather than each route hand-rolling its own ownership filter — this
   directly addresses the "ownership-scoping bug" risk flagged in
   Section 10/16 (Phase 2): there's exactly one place this logic lives,
   not thirty places it could be gotten wrong independently.
3. **Every child-entity query (Experience, Achievement, Skill evidence,
   etc.) joins through `CareerProfile.user_id == current_user.id`** —
   never queries a child table by its own ID alone without that join,
   even though it would often "work" without it (the row exists) —
   the join is what prevents User A from reading or editing User B's
   row 42 just because they guessed or enumerated the ID.
4. **No admin/role concept in the MVP** — every user only ever accesses
   their own data; there's no support-staff or admin read path proposed
   here, consistent with Decision 6's minimal-data-collection principle
   and simply not a stated requirement anywhere in the brief.

---

## 29. Deliverable F — Privacy / Consent User Flow

**Recommendation**, directly implementing Decision 6.

1. **Anonymous use of the six existing tools is completely unaffected.**
   No login prompt, no consent screen, nothing changes for anyone who
   never visits the Career Profile area — this is the literal meaning of
   "opt-in," not a soft suggestion.
2. **A visitor who wants a Career Profile clicks into that area and is
   prompted to sign up or log in** (Deliverable C's custom pages).
   Successfully creating a Cognito account creates an internal `User`
   row — but **`consent_given_at` is still null at this point.** Having
   an account and having consented to Career Profile data storage are
   two separate, deliberately un-conflated facts (Section 13).
3. **On first entry to the actual Career Profile area, before any CRUD
   form, upload field, or AI suggestion is shown**, a plain-language
   consent screen states, specifically and concretely (not buried in a
   general Terms of Service link):
   - What will be stored (their career history, skills, education, etc.
     — named plainly, not just "your data").
   - Why (so tools like Right Fit can compare against their whole
     career, not just one uploaded resume — tied back to the actual
     stated purpose, not generic boilerplate).
   - That nothing becomes part of their profile without their explicit
     confirmation, even when the AI suggests it (restating the brief's
     own core promise back to the user, since it's the single most
     reassuring, concrete thing this screen can say).
   - Their rights: review, edit, export, and delete their data — stated
     as real rights on this screen itself, not deferred to a settings
     page they'd have to go find.
4. **Only an explicit, affirmative action** — a real, clearly-labeled
   button ("Yes, save my career information") — **sets
   `consent_given_at`** and creates the `CareerProfile` row. No
   pre-checked box, no "continuing implies consent" framing.
5. **Before `consent_given_at` is set, no Career Profile data can be
   written** — enforced by Deliverable E's `get_career_profile_or_404`
   helper naturally, since there's no `CareerProfile` row to write
   children onto yet; the consent gate isn't just a UI screen, it's a
   genuine data-model precondition.
6. **Review/edit/export/delete**, per Decision 6's "users must eventually
   be able to" language — explicitly **not required for the MVP launch
   itself**, but the data model (Section 13) and the ownership pattern
   (Deliverable E) are both already shaped so that adding these later is
   straightforward: export is "serialize everything under this
   `CareerProfile`," delete is "cascade-delete everything under this
   `CareerProfile`" (plus the `User.deleted_at` soft-delete for the
   account itself) — no schema rework needed when this is built.

---

## 30. Deliverable G — Proposed Folder / File Structure

**Recommendation**, following the existing codebase's established
convention (one module per concern) rather than introducing an
unfamiliar structure.

### Backend

```
backend/
  main.py                 UNCHANGED entry point; gains CORS tightening
                           (Phase 0) and new router includes (Phase 1+)
  auth/
    __init__.py
    cognito.py             JWKS fetching/caching, JWT verification
    dependencies.py         get_current_user() - the one "internal
                             interface" every protected route depends on
  db.py                    SQLAlchemy engine/session setup - the first
                           database connection this codebase will have
  models/
    __init__.py
    user.py                User
    career_profile.py       CareerProfile, Experience, Achievement,
                             GeographicExperience, IndustryExperience,
                             Education, Certification, Language,
                             JobPreference
    skill.py                Skill, SkillAlias, ExperienceSkill,
                             CertificationSkill, Technology,
                             ExperienceTechnology
    resume.py                ResumeVersion, JobAnalysis
  career/
    __init__.py
    routes.py                /api/career/* endpoint definitions
    ingestion.py             resume upload -> extract (reuses
                             extractor.py unchanged) -> restructure
                             (reuses the Phase 0 shared extraction
                             function) -> candidate evidence rows
    verification.py           accept/reject/edit endpoints, generalizing
                             elevate.py's confirm-facts pattern
    matching.py                Phase 5+: Career Match / Resume Coverage
                             (not built in Phase 0-4)
  resume_ingestion.py       NEW in Phase 0 - the extracted shared
                           "restructure resume text into JSON" function,
                           consumed by career/ingestion.py; the six
                           existing tools are NOT changed to use it yet
  migrations/                Alembic migration scripts
  # existing files below, entirely unchanged:
  coach.py, upgrade.py, scratch.py, elevate.py, profile_review.py,
  prepare.py, extractor.py, resume_builder.py, llm_utils.py,
  requirements.txt
```

### Frontend

**Note:** this is the one deliberate departure from the site's existing
flat `frontend/*.html` convention — justified specifically by Decision
3's instruction to organize the new JS into focused modules, which a
flat structure doesn't naturally support once there are this many
distinct concerns.

```
frontend/
  career/
    login.html
    register.html
    consent.html              the Deliverable F screen, its own page
                             so it can never be skipped by a direct link
    profile.html               the main Career Profile dashboard/CRUD UI
    verify.html                  the accept/reject/edit evidence-review UI
    js/
      auth.js                  Cognito sign-in/sign-up calls
                             (amazon-cognito-identity-js), token storage
      api.js                    shared fetch() helper that attaches the
                             bearer token - the one place every career/
                             page's API calls flow through
      experienceForm.js          manual CRUD form logic for Experience/
                             Education/Certification/Language
      evidenceReview.js          the accept/reject/edit UI logic,
                             generalized from elevate.js's
                             renderDiscoveredFacts() pattern
      consentFlow.js             the Deliverable F consent-screen logic
  # existing files below, entirely unchanged:
  index.html, tool.html, scratch.html, elevate.html, spotlight.html,
  prepare.html, learn.html, article.html, videos.html, about.html,
  app.js, scratch.js, elevate.js, spotlight.js, prepare.js, guide.js,
  loading.js, markdown.js, style.css
```

   decision for that phase, not resolved here.
