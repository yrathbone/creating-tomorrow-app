# Creating Tomorrow — AWS Migration Plan

**This is a plan, not an action.** Nothing in this document has been built.
No AWS resources exist because of this document. Render, Cloudflare, GoDaddy
DNS, and the current production site are all untouched and should remain the
live, working version until you decide otherwise, stage by stage.

This plan is built directly from the verified facts in
`docs/CURRENT_INFRASTRUCTURE.md` — in particular: **no database, no
persistence anywhere, no authentication, stateless request/response, plain
HTML/JS frontend with no build step.** That's an unusually simple starting
point, and the recommendation below leans into that rather than adding
complexity the current app doesn't have.

---

## Update, 2026-09-22 — App Runner deprecated; backend recommendation changed

Two real, verified events on the night Stage 2 was actually run, worth
recording plainly since they changed this plan's backend recommendation:

1. **AWS App Runner stopped accepting new customers as of 2026-04-30**
   (moved to maintenance mode 2026-03-31) — discovered live, in the AWS
   console, not from this document. App Runner's own console banner
   states existing customers are unaffected, but a *new* service (ours)
   genuinely cannot be created there anymore. AWS's own stated
   replacement is **Amazon ECS Express Mode** (launched 2025-11-21).
2. **ECS Express Mode was built, tested, and verified working end-to-end
   tonight** — a real container image was built in AWS CloudShell from a
   `Dockerfile` (now in this repo's root), pushed to ECR, and deployed as
   an Express Mode service. `curl` against the live service's
   `/api/health` and `/` both returned 200, confirming the actual
   FastAPI app was serving real traffic on AWS. It was then deliberately
   **deleted** the same night, for the reason below.
3. **The real cost was higher than this document originally estimated,
   and recurring.** ECS Express Mode provisions a dedicated Application
   Load Balancer alongside the Fargate task for each service — combined
   with 1 vCPU/2 GB of always-on Fargate compute, this runs to roughly
   **$50+/month if left running**, not the $35-40/month this document
   originally estimated for App Runner alone (App Runner's own pricing
   page, still visible on its console, lists $0.064/vCPU-hour +
   $0.007/GB-hour compute - ECS Express Mode's Fargate pricing is
   similar, plus the ALB's separate hourly charge on top). Given the
   project's real, stated budget constraints, this is not an acceptable
   *persistent* architecture.

**What changed as a result:** the backend hosting recommendation below
moved from App Runner to **Lambda + API Gateway** — not because it's the
"better" AWS service in the abstract, but because Lambda's free tier is
**verified permanent** (1M requests + 400,000 GB-seconds/month, forever,
not a 12-month trial - confirmed via AWS's own current documentation),
making it realistically **$0/month** at this app's actual traffic level,
indefinitely. ECS/Fargate remains a legitimate thing to learn - it now
sits in this plan as an occasional, deliberate **practice rep** (spin up,
verify, screenshot, tear down - exactly what happened tonight) rather
than the architecture that stays running. The Backend hosting section
below has been rewritten to reflect this; App Runner's writeup is kept
for historical context but is no longer a real option.

---

## PHASE 4 — Evaluating the AWS options

### Frontend hosting

**AWS Amplify Hosting**
- WHAT IT IS: A managed static-site host with built-in CI/CD — connect a
  GitHub repo, it builds and deploys on push.
- WHAT IT WOULD REPLACE: Render's `StaticFiles` serving of `frontend/`.
- WHY WE WOULD USE IT: Closest match to "push to GitHub, it just deploys" —
  the workflow you already have with Render. Handles HTTPS, custom domains,
  and CDN distribution automatically without you configuring each piece.
- WHY WE MIGHT NOT: It's one more managed service with its own concepts
  to learn (build settings, redirects config) — S3+CloudFront teaches you
  the underlying pieces more directly.
- COST/COMPLEXITY: Low cost for a site this size (static files only,
  low traffic). Low-moderate complexity — mostly point-and-click.
- LEARNING VALUE: Moderate — teaches you managed hosting patterns, but
  hides the S3/CDN mechanics underneath.
- MIGRATION DIFFICULTY: Low — this app's frontend has no build step, so
  Amplify would essentially just be serving the `frontend/` folder as-is.
- PRIVACY: No change — same static files, same lack of user data.

**S3 + CloudFront**
- WHAT IT IS: S3 is object storage (you can point it at a folder of files
  and serve them over HTTP); CloudFront is AWS's CDN, sitting in front of
  S3 to cache and serve content close to each visitor.
- WHAT IT WOULD REPLACE: Same as above — Render's static file serving.
- WHY WE WOULD USE IT: You explicitly want to learn AWS hands-on. This
  path teaches you two fundamental, widely-reused AWS services directly,
  rather than through Amplify's abstraction. It's also the more standard
  "textbook" static-hosting pattern you'll see referenced everywhere.
- WHY WE MIGHT NOT: More manual setup — you configure the S3 bucket
  policy, the CloudFront distribution, cache invalidation on deploy, and
  (if you want auto-deploy-on-push) your own small CI step to sync files
  to S3. More moving parts to understand, which is either a pro or a con
  depending on your goal that week.
- COST/COMPLEXITY: Very low cost (pennies/month for a site this size).
  Moderate complexity to set up correctly the first time (bucket
  permissions are a classic AWS gotcha — public-read on a static site
  bucket needs to be configured deliberately, not accidentally).
- LEARNING VALUE: High — S3 and CloudFront are two of the most
  fundamental AWS services, used constantly across almost any AWS
  architecture you'll build later.
- MIGRATION DIFFICULTY: Low-moderate.
- PRIVACY: No change.

**Recommendation:** Given priority #1 is "learn AWS hands-on" and priority
#7 is "understand every AWS component before using it," **S3 + CloudFront**
is the better fit *if you want to slow down and really learn each piece*.
Amplify is the better fit if you'd rather have one moving part instead of
two. Either is a completely reasonable choice — this is genuinely a matter
of which kind of learning experience you want first. (See the "MIGRATION
FIRST STEP" in the executive summary for a suggested way to decide without
overthinking it.)

---

### Backend hosting

**AWS App Runner — NOT AVAILABLE, kept for historical context only**
- WHAT IT WAS: A managed service that ran a containerized (or
  source-code-based) web app for you — closest AWS equivalent to what
  Render already does. This plan originally recommended it as the
  smallest conceptual jump from Render.
- **STATUS, VERIFIED 2026-09-22: stopped accepting new customers as of
  2026-04-30.** Existing App Runner customers are unaffected, but a new
  service cannot be created. AWS's own stated replacement is Amazon ECS
  Express Mode (below). Left in this document so the reasoning trail -
  and the lesson that a service can disappear between when a plan is
  written and when it's actually executed - stays visible.

**Amazon ECS Express Mode — tested tonight, not recommended for
persistent use**
- WHAT IT IS: A simplified mode inside Amazon ECS, launched 2025-11-21
  specifically as AWS's answer to App Runner's closure. You provide a
  pre-built container image (from ECR) plus two IAM roles; it
  auto-provisions the cluster, Fargate task, Application Load Balancer,
  target groups, security groups, and auto-scaling policy as one unit.
- WHAT IT WOULD REPLACE: Render's `uvicorn main:app` process.
- WHY WE WOULD USE IT: Genuinely the closest thing to App Runner's
  "point it at something, get a URL" experience that AWS currently
  offers for containers. Real, valuable ECS/Fargate/container-networking
  exposure - a different skill than serverless, worth having.
- WHY WE MIGHT NOT, AND WHY THIS IS THE DECIDING FACTOR HERE: **it has no
  source-build step at all** - a `Dockerfile`, a local/CloudShell
  `docker build` + `docker push` to ECR, is a hard prerequisite every
  time, unlike Render, App Runner, or Lambda's deploy-from-source
  options. More importantly: **it has no meaningful free tier and runs
  continuously** - verified tonight, a 1 vCPU/2 GB service plus its
  dedicated Application Load Balancer runs to roughly **$50+/month if
  left running**, confirmed by actually building, deploying, and pricing
  this out live rather than estimating from documentation.
- COST/COMPLEXITY: High ongoing cost if left running (see above). The
  one-time cost of a build-test-teardown cycle (a few hours of Fargate +
  ALB time) is closer to $1-2.
- LEARNING VALUE: High for containers/ECS/Fargate/load-balancing
  specifically - a genuinely different, valuable pattern from serverless.
- MIGRATION DIFFICULTY: Moderate (Dockerfile + ECR push each deploy;
  no auto-deploy-on-push without adding a separate GitHub Actions
  pipeline, unlike this app's current Render workflow).
- PRIVACY: No change to app behavior.
- **Recommended use going forward:** occasional, deliberate practice
  reps only - build, verify it works end-to-end, screenshot/document it,
  delete it same session. Not the architecture that stays live.

**Lambda + API Gateway — now the primary recommendation**
- WHAT IT IS: Lambda runs your code only when a request comes in (no
  always-on server); API Gateway is the piece that turns HTTP requests
  into Lambda invocations and routes them.
- WHAT IT WOULD REPLACE: Render's always-on uvicorn process.
- WHY WE WOULD USE IT: Can be the cheapest option at low/irregular
  traffic (pay per request, not per hour) — and teaches you a
  fundamentally different, very widely-used AWS pattern (serverless).
- WHY WE MIGHT NOT: FastAPI wasn't originally designed for this model —
  you'd need an adapter (e.g. Mangum) to translate between API Gateway's
  event format and FastAPI's expectations. "Cold starts" (the first
  request after idle time is slower while Lambda spins up) matter for a
  tool where people are actively waiting ~30-60 seconds for an AI
  response already — an extra few hundred ms to a couple seconds of cold
  start stacks on top of that. More moving parts to get right (IAM
  permissions between API Gateway and Lambda, packaging Python
  dependencies for Lambda's environment, timeout limits — Lambda has a
  maximum execution time that a slow Claude API response could
  realistically approach).
- COST/COMPLEXITY, UPDATED 2026-09-22: **verified, not estimated** -
  Lambda's free tier (1M requests + 400,000 GB-seconds/month) is
  permanent, not a 12-month trial, confirmed against AWS's own current
  documentation. At this app's real traffic level, realistically
  **$0/month, indefinitely**. Higher setup complexity than a plain
  container (the Mangum adapter layer), but that one-time complexity
  cost is now clearly worth it against ECS Express Mode's $50+/month if
  left running.
- LEARNING VALUE: High — serverless is a core AWS pattern worth
  understanding, this app's statelessness genuinely suits it, and
  "serverless-first API design" reads as a stronger architectural
  decision in an interview than "I containerized it," specific and
  defensible on cost grounds.
- MIGRATION DIFFICULTY: Moderate — requires an adapter layer and careful
  timeout/dependency-packaging work, though no application logic changes.
- PRIVACY: No change.

**ECS/Fargate (full manual control, not Express Mode)**
- WHAT IT IS: The same underlying ECS/Fargate engine Express Mode uses,
  but with every piece (VPC, load balancer, task definitions, scaling
  rules) configured by hand instead of auto-provisioned.
- WHY WE WOULD USE IT: Only once fine-grained control is actually
  needed - multiple services, custom networking, specific compliance
  requirements. This app has none of those needs today.
- WHY WE MIGHT NOT: Same cost profile as Express Mode (verified tonight -
  see above) plus meaningfully higher setup complexity, for no
  functional benefit this app currently needs. Priority #4 ("avoid
  unnecessary complexity") argues directly against this for now.
- LEARNING VALUE: Very high, eventually - advanced-tier AWS networking
  (VPCs, subnets, security groups) - but a deliberate later project, not
  a fit for this app's actual requirements today.
- MIGRATION DIFFICULTY: High relative to Lambda or Express Mode.
- PRIVACY: No change to app behavior; more infrastructure surface to
  secure correctly.

**Recommendation, UPDATED 2026-09-22: Lambda + API Gateway.** App Runner
is no longer available to new customers (verified above). Between the two
remaining real options, Lambda's permanently-free tier directly serves
the project's actual, stated budget constraint in a way ECS Express Mode's
$50+/month cannot - this is now the deciding factor, ahead of "smallest
conceptual jump from Render." ECS Express Mode remains valuable, but as
an occasional practice rep (build, verify, screenshot, delete - as done
tonight), not the architecture that stays live. Full manual ECS/Fargate
stays a later, deliberate "now I want to learn VPCs" project, same as
before.

---

### Secrets

**AWS Secrets Manager**
- WHAT IT IS: Stores secrets (like `ANTHROPIC_API_KEY`) encrypted, with
  access controlled by IAM, and (unlike Parameter Store) built-in
  automatic rotation support.
- WHAT IT WOULD REPLACE: Render's dashboard-set environment variable.
- WHY WE WOULD USE IT: The "correct," most commonly recommended AWS
  pattern for API keys; teaches you IAM permission scoping (which service
  can read which secret).
- WHY WE MIGHT NOT: Has a small ongoing per-secret cost (a few
  dollars/month) — for exactly one secret, this is a case where the
  "proper enterprise" tool costs more than the problem strictly requires.
- COST/COMPLEXITY: Low-moderate ongoing cost for the number of secrets
  this app actually has (one). Moderate setup complexity (IAM policy
  writing).
- LEARNING VALUE: High — IAM is central to almost everything else you'll
  do in AWS, and this is a low-stakes place to practice it.

**AWS Systems Manager Parameter Store**
- WHAT IT IS: A simpler key-value store that can also hold secrets
  (as `SecureString` parameters, encrypted via KMS), without Secrets
  Manager's rotation features.
- WHAT IT WOULD REPLACE: Same as above.
- WHY WE WOULD USE IT: Free (standard tier) for exactly this kind of
  single-value use case, still teaches IAM/KMS basics, with less
  ceremony than Secrets Manager.
- WHY WE MIGHT NOT: If you later want automatic key rotation, you'd
  migrate to Secrets Manager anyway.
- COST/COMPLEXITY: Free at this scale. Low complexity.
- LEARNING VALUE: High, same IAM lessons as Secrets Manager, lower cost.

**Recommendation: Parameter Store to start.** One secret, no rotation need
today, priority #5 (minimize cost) applies directly. This is genuinely a
"you can always upgrade later" decision — moving one secret from Parameter
Store to Secrets Manager later is a small, low-risk change, not a
re-architecture.

---

### Monitoring

**CloudWatch**
- WHAT IT IS: AWS's built-in logging, metrics, and alerting service —
  every AWS compute service (App Runner, Lambda, ECS) sends its logs here
  by default.
- WHAT IT WOULD REPLACE: Render's built-in dashboard logs (there's no
  direct prior tool to "replace," since this app has no separate
  monitoring today — worth naming honestly rather than implying
  otherwise).
- WHY WE WOULD USE IT: It's not really optional — whichever compute
  service you pick (Lambda especially) sends logs to CloudWatch
  automatically. The real decision is just how much you configure beyond
  the default (custom metrics, alarms, dashboards).
- WHY WE MIGHT NOT: You could choose not to set up alarms/dashboards
  initially and just use the default log viewing — that's a completely
  fine minimal starting point.
- COST/COMPLEXITY: Low at this traffic level (a free tier covers a
  meaningful amount of log volume for a low-traffic app). Low complexity
  for basic log viewing; moderate if you build custom dashboards/alarms.
- LEARNING VALUE: High and, practically, unavoidable — you'll be reading
  CloudWatch logs the first time anything breaks on Lambda, whether
  or not you "set it up" deliberately.
- PRIVACY: Given `coach.py`/`upgrade.py`/`profile_review.py` already log
  category-only failure diagnostics (never resume/job-posting text), a
  sensible practice when migrating is to preserve that same discipline in
  whatever CloudWatch logging you add — don't let application-level logs
  become a new place PII ends up, even unintentionally, at the
  infrastructure layer.

**Recommendation: Use CloudWatch's default logging from day one** (it comes
free with Lambda), and defer custom alarms/dashboards until you
actually want to be paged about something specific — that's a natural
Stage 8/9 task, not a Stage 3 one.

---

### Cost governance — added 2026-09-22, from tonight's real experience

Not an AWS service to choose, but a practice worth making standard across
every stage from here on, learned directly from tonight's ECS Express Mode
test:

- **A budget alert is not a safety net — it's a notification you might not
  see in time.** The $10 zero-spend budget set up in Stage 2 only emails
  you; it doesn't stop anything. AWS Budgets also supports **budget
  actions** — a rule that can automatically apply a restrictive IAM policy
  or stop specific resources the moment a real dollar threshold hits.
  Worth setting one up as an actual backstop, not just an alert.
- **Tag every resource with something like `project=creating-tomorrow`**
  as you create it, so Cost Explorer can show spend filtered to exactly
  this project — real per-project visibility instead of guessing which
  line item is this app versus general account activity.
- **Default to "spin up, verify, document, tear down" for anything
  compute-heavy that isn't already free-tier-safe** (Lambda, S3,
  CloudFront all qualify as safe-to-leave-running at this app's scale;
  ECS/Fargate, EC2, and anything with a load balancer do not). This
  isn't a workaround — cleanly provisioning and de-provisioning
  infrastructure is a real, legitimate skill in its own right.

---

### Media (S3)

The app has three static images (`logo-icon.png`, `guide-mascot.png`,
`hero-people.jpg`) and no user-uploaded media storage of any kind (resumes
and screenshots are processed in memory and never saved — see
`CURRENT_INFRASTRUCTURE.md` Section E). If the frontend moves to S3+CloudFront,
these three images simply live in that same bucket — there's no separate
"media" decision to make here. **No dedicated media-storage AWS service is
needed beyond whatever bucket already hosts the frontend.**

---

### Authentication (Cognito)

**Not recommended today.** The app has no user accounts, no login, no
per-user data of any kind — every tool is stateless and anonymous. Per your
own priority list ("Cognito ONLY if user accounts become necessary"),
there's no current justification for it. If the product ever adds saved
history, favorites, or accounts, this section should be revisited — but
adding it now would be complexity in search of a requirement.

---

### Database (RDS PostgreSQL)

**Not recommended today**, and this is worth being direct about: the
current application provably has **zero** persistent state anywhere in its
own code (verified in `CURRENT_INFRASTRUCTURE.md` Section E — no database
driver, no db import, nothing written to disk). Adding RDS to this
migration would be adding an entire category of infrastructure (VPC
subnet groups, backup policies, connection pooling, a whole new class of
security surface for PII) that the application does not use and was not
designed around. Per your own priorities #6 ("minimize storage of
resumes/job descriptions") and #14 ("do not assume we even need a
database until current usage is verified") — usage has now been verified,
and the answer is that none is needed. If a future feature genuinely
requires persistence (saved sessions, accounts, history), that's the
moment to reopen this section, size the actual need, and choose
accordingly — not before.

---

### DNS

Per your explicit priorities: **keep GoDaddy** for the DNS records that
matter right now (this is independent of where the backend/frontend are
hosted — DNS just points at whichever IP/hostname is live). **Route 53**
would only make sense later if you specifically wanted tighter integration
with other AWS services that benefit from Route 53-managed DNS (e.g.
certain health-check-based failover patterns) — there's no such need
visible in this application today, so this section proposes no change for
the foreseeable stages.

---

## Overall AWS recommendation

**The simplest architecture that safely runs this exact application:**

```
Frontend:  S3 + CloudFront  (or Amplify Hosting, if you'd rather have one
                              moving part instead of two — see Frontend
                              section above)
Backend:   Lambda + API Gateway (UPDATED 2026-09-22 — App Runner no longer
                              available to new customers; Lambda's
                              permanently-free tier keeps this at ~$0/month
                              at this app's traffic, vs. ECS Express Mode's
                              verified $50+/month if left running)
Secrets:   Parameter Store   (one secret, no rotation need yet)
Monitoring: CloudWatch default logging (comes with Lambda automatically)
Database:  none              (verified not needed)
Auth:      none               (verified not needed)
DNS:       stays on GoDaddy   (independent of hosting; no reason to move yet)
```

This is deliberately **not** the most "enterprise" architecture available —
per your own stated priority, complexity should be added only when a real
requirement demands it, not by default.

---

## PHASE 5 — Migration roadmap

Each stage is something you do, understand, and can verify before moving to
the next. Render stays live and untouched through every stage until Stage 10.

### STAGE 0 — Freeze current QA-complete release
- **WHAT I WILL DO:** Nothing new — this stage just names the current state
  (the QA-complete baseline referenced at the top of this assignment) as
  the known-good point to migrate *from*.
- **WHAT I WILL LEARN:** Nothing new; this is a checkpoint.
- **FILES INVOLVED:** None changed.
- **AWS SERVICE:** None.
- **HOW TO TEST IT:** Confirm `creatingtomorrow.net` currently works end to
  end (already true).
- **ROLLBACK PLAN:** N/A.
- **COMPLEXITY:** Beginner.

### STAGE 1 — Understand/inventory current application
- **WHAT I WILL DO:** This is exactly what this assignment's Phases 1-3
  produced — `docs/CURRENT_INFRASTRUCTURE.md`,
  `docs/HOW_CREATING_TOMORROW_WORKS.md`,
  `architecture/creating_tomorrow_architecture.py`.
- **WHAT I WILL LEARN:** The real shape of your own application, verified
  rather than assumed.
- **FILES INVOLVED:** The three files above (already created).
- **AWS SERVICE:** None yet.
- **HOW TO TEST IT:** Read `creating_tomorrow_architecture.py`'s output and
  confirm it matches your own understanding; flag anything that looks
  wrong.
- **ROLLBACK PLAN:** N/A — this stage is purely documentation.
- **COMPLEXITY:** Beginner.

### STAGE 2 — Create AWS account/security baseline
- **WHAT I WILL DO:** Create an AWS account (if you don't have one), set up
  MFA on the root user, create an IAM user/role for yourself with
  appropriate permissions (never use the root account for day-to-day work),
  and set a budget alert.
- **WHAT I WILL LEARN:** IAM fundamentals — users, roles, policies — and
  why the root account is set aside as a break-glass-only credential.
- **FILES INVOLVED:** None in this repo.
- **AWS SERVICE:** IAM, AWS Budgets.
- **HOW TO TEST IT:** Log in as the IAM user (not root) and confirm you can
  do your intended work; confirm a budget alert email arrives when
  manually testing the threshold.
- **ROLLBACK PLAN:** Delete the IAM user/role if something's misconfigured
  — no application impact either way.
- **COMPLEXITY:** Beginner.

### STAGE 3 — Deploy frontend copy to AWS
- **WHAT I WILL DO:** Upload a copy of `frontend/` to S3 (or connect the
  repo to Amplify), configure CloudFront (if using S3), get a working
  `*.cloudfront.net` (or Amplify-provided) URL.
- **WHAT I WILL LEARN:** S3 bucket policies, static website hosting,
  CloudFront distributions and caching — or, if Amplify, managed
  build/deploy pipelines.
- **FILES INVOLVED:** All of `frontend/` (read-only copy — nothing in the
  repo changes).
- **AWS SERVICE:** S3, CloudFront (or Amplify Hosting).
- **HOW TO TEST IT:** Load the AWS-hosted URL directly and confirm pages
  render — API calls will fail at this stage since there's no backend yet
  behind this frontend copy, and that's expected.
- **ROLLBACK PLAN:** Delete the S3 bucket/CloudFront distribution (or
  Amplify app) — zero impact on Render, which is still serving the real
  site.
- **COMPLEXITY:** Beginner-Moderate.

### STAGE 4 — Keep current backend on Render
- **WHAT I WILL DO:** Nothing — explicitly confirming Render keeps serving
  `creatingtomorrow.net` throughout Stages 3, 5, 6, 7. This stage exists
  as a checkpoint, not an action.
- **WHAT I WILL LEARN:** Nothing new.
- **FILES INVOLVED:** None.
- **AWS SERVICE:** None.
- **HOW TO TEST IT:** `creatingtomorrow.net` still works, unchanged.
- **ROLLBACK PLAN:** N/A.
- **COMPLEXITY:** Beginner.

### STAGE 5 — Test AWS frontend against existing backend
- **WHAT I WILL DO:** Point the AWS-hosted frontend copy's API calls at the
  *existing* Render backend (e.g. by temporarily hardcoding the Render URL,
  or configuring CORS on Render to allow the CloudFront/Amplify origin —
  Render's CORS is already wide open (`allow_origins=["*"]"`, verified in
  `CURRENT_INFRASTRUCTURE.md`), so this should work without a Render
  config change).
- **WHAT I WILL LEARN:** How frontend/backend separation and CORS actually
  work in practice, with a real cross-origin setup.
- **FILES INVOLVED:** A temporary/local copy of the frontend JS files
  pointing at an absolute Render URL instead of relative `/api/...` paths
  — not committed to the real repo unless you decide to make this
  permanent.
- **AWS SERVICE:** (reuses Stage 3's S3/CloudFront or Amplify setup).
- **HOW TO TEST IT:** Use a real tool (e.g. Prepare, since it's stateless
  and simple) end-to-end from the AWS-hosted frontend and confirm you get
  a real Claude response back through the existing Render backend.
- **ROLLBACK PLAN:** Discard the temporary frontend copy — no impact on
  either Render or the real repo.
- **COMPLEXITY:** Moderate.

### STAGE 6 — Deploy FastAPI copy to AWS
- **UPDATED 2026-09-22:** rewritten for Lambda + API Gateway (App Runner
  unavailable to new customers — see the update note near the top of this
  document). A separate, already-completed practice rep exists too: the
  app was containerized (`Dockerfile`, repo root) and deployed to ECS
  Express Mode the same night, verified working via `/api/health`, then
  deleted — real experience banked, without adopting it as this stage's
  persistent target.
- **WHAT I WILL DO:** Add a Lambda-compatible entry point using the
  Mangum adapter (wraps the existing FastAPI `app` object from
  `backend/main.py` so API Gateway's event format can invoke it —
  no changes to any tool module or route logic), package
  `backend/requirements.txt`'s dependencies for Lambda's environment,
  create the Lambda function and an API Gateway HTTP API in front of it,
  set `ANTHROPIC_API_KEY` as a Lambda environment variable (Stage 8
  formalizes this into Parameter Store).
- **WHAT I WILL LEARN:** How an existing ASGI app (FastAPI) adapts to a
  request/response model that wasn't originally built for it; API
  Gateway routing; Lambda's dependency-packaging model (zip/layer or
  container image); cold-start behavior in practice, measured against
  this app's own ~15-90s AI response times.
- **FILES INVOLVED:** A new small Lambda handler file (does not modify
  `backend/main.py` or any tool module) — doesn't affect Render.
- **AWS SERVICE:** Lambda, API Gateway.
- **HOW TO TEST IT:** Hit the API Gateway URL's `/api/health` endpoint
  directly and confirm `{"status": "ok", "api_key_configured": true}`;
  separately, time a cold-start request vs. a warm one to see the real
  gap, not a guessed one.
- **ROLLBACK PLAN:** Delete the Lambda function and API Gateway — zero
  impact on Render. (Unlike ECS Express Mode, there's no ongoing cost
  risk to "forgetting" to clean this up if it's ever left running by
  mistake, since Lambda only bills for actual invocations.)
- **COMPLEXITY:** Moderate.

### STAGE 7 — Test AWS backend
- **WHAT I WILL DO:** Point the Stage 3 AWS frontend copy at the Stage 6
  AWS backend instead of Render, and run all six tools end to end.
- **WHAT I WILL LEARN:** Whether the containerized backend behaves
  identically to Render in practice — response times, error handling,
  file upload handling (multipart forms specifically, since that's used
  by 5 of 6 tools).
- **FILES INVOLVED:** None changed — this is testing, not building.
- **AWS SERVICE:** (reuses Stage 3 + Stage 6).
- **HOW TO TEST IT:** Manually run each of the six tools' full flow (per
  `CURRENT_INFRASTRUCTURE.md` Section C) against the all-AWS setup, with
  real (or realistic test) resume/job-posting inputs, and compare results
  to the same inputs against the current Render site.
- **ROLLBACK PLAN:** Keep using Render (already true) — nothing to roll
  back.
- **COMPLEXITY:** Moderate.

### STAGE 8 — Configure secrets/logging/privacy
- **WHAT I WILL DO:** Move `ANTHROPIC_API_KEY` from a plain env var into
  Parameter Store (or Secrets Manager, per your decision above); confirm
  CloudWatch is capturing Lambda's logs; explicitly verify (don't
  assume) that nothing in the AWS logging pipeline captures full
  resume/job-posting text — matching the same discipline already in
  `coach.py`/`upgrade.py`/`profile_review.py`'s `_diagnose()` functions.
- **WHAT I WILL LEARN:** IAM policies scoped to "this Lambda function
  can read this one parameter, nothing else"; CloudWatch log inspection.
- **FILES INVOLVED:** Possibly a small change to how `main.py`'s tool
  modules read `ANTHROPIC_API_KEY` — likely none needed, since
  `os.environ.get(...)` works the same regardless of whether Lambda
  populated that env var from a plain value or from Parameter Store.
- **AWS SERVICE:** Parameter Store (or Secrets Manager), IAM, CloudWatch.
- **HOW TO TEST IT:** Trigger a real tool failure (e.g. an intentionally
  malformed request) and read the resulting CloudWatch log entry —
  confirm it contains a category label, not resume content.
- **ROLLBACK PLAN:** Revert to a plain env var if Parameter Store
  integration causes issues — no impact on Render.
- **COMPLEXITY:** Moderate.

### STAGE 9 — Full regression test
- **WHAT I WILL DO:** Run the same kind of thorough QA this project has
  already done once (all six tools, real/realistic inputs, mobile check,
  privacy check) against the fully-AWS setup (Stage 3 frontend + Stage 6
  backend + Stage 8 secrets/logging), before touching DNS.
- **WHAT I WILL LEARN:** Whether the migration actually preserved
  behavior, not just "whether it technically responds."
- **FILES INVOLVED:** None changed — testing only.
- **AWS SERVICE:** (reuses everything above).
- **HOW TO TEST IT:** Same QA rigor as the original baseline — this is the
  gate before Stage 10, not optional.
- **ROLLBACK PLAN:** Stay on Render if regression testing finds real
  issues — no deadline pressure to cut over before this passes.
- **COMPLEXITY:** Moderate.

### STAGE 10 — DNS cutover
- **WHAT I WILL DO:** In GoDaddy's DNS settings, point `creatingtomorrow.net`
  at the new AWS frontend (CloudFront/Amplify) instead of Render.
- **WHAT I WILL LEARN:** How DNS cutovers actually work in practice — TTLs,
  propagation delay, and why you test thoroughly *before* this step rather
  than after.
- **FILES INVOLVED:** None in this repo — this is a DNS dashboard change.
- **AWS SERVICE:** (whatever Stage 3 chose), GoDaddy DNS.
- **HOW TO TEST IT:** After propagation, load `creatingtomorrow.net`
  directly and confirm it's being served by AWS (check response headers —
  no more `Server: cloudflare`-via-Render, no more `x-render-origin-server`).
- **ROLLBACK PLAN:** **This is the one stage with real risk** — revert the
  DNS record back to Render's value. Keep the old DNS record's value
  written down before changing it. This is exactly why Stage 11 exists.
- **COMPLEXITY:** Beginner (the DNS change itself is simple) but
  **high-stakes** — this is the one step that's live/visible.

### STAGE 11 — Keep Render available temporarily for rollback
- **WHAT I WILL DO:** Leave the Render service running (don't delete it,
  don't cancel it) for an agreed window after cutover — long enough to be
  confident (days, not hours) — purely as an instant rollback target.
- **WHAT I WILL LEARN:** Nothing new technically — this is operational
  discipline, and it's the safety net that makes Stage 10 low-risk instead
  of high-risk.
- **FILES INVOLVED:** None.
- **AWS SERVICE:** None (this stage is about Render, deliberately).
- **HOW TO TEST IT:** Periodically confirm the Render deployment still
  works on its `*.onrender.com` URL during the window.
- **ROLLBACK PLAN:** This stage *is* the rollback plan for Stage 10.
- **COMPLEXITY:** Beginner.

---

## A note on what's NOT in this plan

Per your explicit instructions, this plan does not include: migrating the
older free-text-JSON tools (Beginning/Elevate/Prepare) to the more reliable
`tool_choice` pattern, fixing the unescaped-`innerHTML` frontend pattern, or
adding a database "just in case." Those are real, legitimate follow-up
projects — they're just not AWS migration, and mixing them into this plan
would violate priority #8 (avoid rewriting working code without a reason)
by giving the migration more surface area to go wrong than it needs.
