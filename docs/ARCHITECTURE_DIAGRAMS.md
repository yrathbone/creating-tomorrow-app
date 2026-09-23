# Creating Tomorrow — Architecture Diagrams

Both diagrams below only include components VERIFIED in
`docs/CURRENT_INFRASTRUCTURE.md`. Nothing is shown because it was discussed
previously — only what was actually confirmed by reading the repo or
checking the live site. The proposed diagram's new pieces are explicitly
labeled `PROPOSED` and nothing has been built.

---

## 1. CURRENT architecture (verified)

```mermaid
flowchart TD
    User([Person using the site])
    DNS[GoDaddy DNS<br/>ns63/ns64.domaincontrol.com]
    CF[Cloudflare<br/>fronts the custom domain<br/><i>NEEDS VERIFICATION: separate account,<br/>or Render's own edge network?</i>]
    Render[Render<br/>runs Uvicorn + FastAPI]
    Static[Static frontend<br/>10 HTML pages, plain JS/CSS<br/>served by the same FastAPI process]
    API[FastAPI backend<br/>backend/main.py<br/>13 endpoints]
    Tools[Tool logic modules<br/>coach.py / upgrade.py / scratch.py /<br/>elevate.py / profile_review.py / prepare.py]
    Anthropic[(Anthropic API<br/>Claude - all AI reasoning happens here)]
    Builder[resume_builder.py<br/>python-docx, no AI call]
    GitHub[(GitHub<br/>yrathbone/creating-tomorrow-app)]

    User -->|1. DNS lookup| DNS
    DNS -->|resolves to| CF
    User -->|2. HTTPS request| CF
    CF -->|3. proxies to| Render
    Render --> API
    API -->|non-/api/* routes| Static
    API -->|/api/* routes| Tools
    Tools -->|messages.create| Anthropic
    Anthropic -->|JSON / tool_use response| Tools
    API -->|.docx-generating routes only,<br/>no AI call| Builder
    GitHub -->|git push triggers auto-deploy| Render

    style Anthropic fill:#e8f0ff
    style CF fill:#fff3d6
    style GitHub fill:#f0f0f0
```

**What's deliberately absent from this diagram** (verified, not omitted by
accident): no database, no authentication service, no caching layer, no
message queue, no analytics/tracking service, no file storage service for
user uploads (everything is in-memory per request — see
`CURRENT_INFRASTRUCTURE.md` Section E).

---

## 2. PROPOSED AWS architecture

**Nothing below has been built as a persistent service.** Every AWS box is
explicitly proposed — see `docs/AWS_MIGRATION_PLAN.md` for the full
reasoning behind each choice, including the alternatives that were
considered and why they weren't picked. One exception, noted where it
appears below: Amazon ECS Express Mode was actually built, deployed,
verified working, and deleted on 2026-09-22 as a one-time practice rep —
it is not part of the proposed persistent architecture.

**Updated 2026-09-22:** the backend box changed from AWS App Runner to
Lambda + API Gateway. App Runner stopped accepting new customers as of
2026-04-30 (verified live in the AWS console, not from documentation).

```mermaid
flowchart TD
    User([Person using the site])
    DNS[GoDaddy DNS<br/>NO CHANGE - stays on GoDaddy]
    CF_prop["PROPOSED: CloudFront<br/>(replaces whatever Cloudflare's<br/>current role turns out to be)"]
    S3[PROPOSED: S3 bucket<br/>static frontend files]
    Lambda[PROPOSED: Lambda + API Gateway<br/>runs the same FastAPI app<br/>via a Mangum adapter]
    Tools[Tool logic modules<br/>UNCHANGED Python code<br/>coach.py / upgrade.py / etc.]
    Anthropic[(Anthropic API<br/>UNCHANGED - same external call)]
    Params[PROPOSED: Parameter Store<br/>holds ANTHROPIC_API_KEY]
    CW[PROPOSED: CloudWatch<br/>default Lambda logging]
    GitHub[(GitHub<br/>UNCHANGED - same repo,<br/>now also read by AWS CI/CD)]
    NoDB[["NOT PLANNED: database<br/>(verified not needed today -<br/>see AWS_MIGRATION_PLAN.md)"]]
    NoAuth[["NOT PLANNED: authentication<br/>(no user accounts exist today)"]]
    NoAppRunner[["NOT AVAILABLE: App Runner<br/>(closed to new customers<br/>2026-04-30)"]]
    NoECS[["TESTED THEN DELETED 2026-09-22:<br/>ECS Express Mode<br/>(verified working, but ~$50+/mo<br/>if left running - not persistent)"]]

    User -->|DNS lookup| DNS
    DNS -->|resolves to| CF_prop
    User -->|HTTPS request for pages/assets| CF_prop
    CF_prop -->|serves| S3
    User -->|HTTPS request for /api/*| Lambda
    Lambda --> Tools
    Tools -->|messages.create| Anthropic
    Lambda -.->|reads secret| Params
    Lambda -.->|sends logs| CW
    GitHub -.->|CI/CD deploy| S3
    GitHub -.->|CI/CD deploy| Lambda

    style Anthropic fill:#e8f0ff
    style CF_prop fill:#d6ecff,stroke-dasharray: 5 5
    style S3 fill:#d6ecff,stroke-dasharray: 5 5
    style Lambda fill:#d6ecff,stroke-dasharray: 5 5
    style Params fill:#d6ecff,stroke-dasharray: 5 5
    style CW fill:#d6ecff,stroke-dasharray: 5 5
    style NoDB fill:#f5f5f5,stroke-dasharray: 2 2
    style NoAuth fill:#f5f5f5,stroke-dasharray: 2 2
    style NoAppRunner fill:#f5f5f5,stroke-dasharray: 2 2
    style NoECS fill:#fff3d6,stroke-dasharray: 2 2
```

**Legend:** dashed-border blue boxes = proposed AWS components (not built).
Grey dashed boxes = explicitly considered and **not** recommended today,
shown so the absence is a decision, not an oversight. The amber dashed box
(ECS Express Mode) is different from the rest — it's the one thing in this
diagram that was actually built and verified, then deliberately torn down,
rather than never built at all.

**What does NOT change in this proposal:** the Python code in every
`backend/*.py` tool module, the entire `frontend/` folder's HTML/CSS/JS, the
Anthropic API relationship, and the GoDaddy DNS registrar. The migration
targets *where the code runs*, not *what the code does*.
