# Architecture Learning Checklist

Priorities below are based on the ACTUAL architecture verified in
`docs/CURRENT_INFRASTRUCTURE.md` — e.g. IAM is "learn during migration"
because App Runner (the recommended backend target) requires it
immediately, while RDS is "learn later" because this app verifiably doesn't
use a database.

---

## I UNDERSTAND THIS NOW

*(Based on this session's build/fix work and this audit — adjust freely,
this is a starting estimate, not a test result.)*

- Python application structure (functions, dicts, classes, modules/imports)
- JSON — reading it, writing it, why APIs use it
- REST APIs / HTTP requests (GET vs POST, request body, status codes)
- FastAPI route handlers (`@app.post(...)`, `Form(...)`, `UploadFile`)
- Frontend/backend communication via `fetch()`
- Environment variables and why secrets don't belong in committed files
- Git/GitHub basics (push, commit, and how Render's auto-deploy uses them)
- What a prompt is, and how a system prompt differs from a user prompt

---

## I SHOULD LEARN THIS DURING MIGRATION

*(These map directly to Stage 2 and Stage 6-8 of
`docs/AWS_MIGRATION_PLAN.md` — you'll need them immediately, not
eventually.)*

- **AWS IAM** — users, roles, policies. Needed from Stage 2 onward; almost
  every other AWS service leans on IAM for permissions.
- **Hosting on AWS App Runner specifically** — how it builds/runs a
  container, how it differs from Render's model. Needed for Stage 6.
- **Containers / Dockerfiles** — App Runner can deploy from source code
  directly, but understanding what a container actually is will make every
  later AWS service easier. Needed for Stage 6.
- **S3** — buckets, permissions, static website hosting. Needed for
  Stage 3 (whichever frontend option you pick).
- **CloudFront** — CDN basics, cache invalidation, origins. Needed for
  Stage 3 if you choose S3+CloudFront over Amplify.
- **AWS Systems Manager Parameter Store / Secrets Manager** — how a running
  AWS service reads a secret without it living in code. Needed for Stage 8
  (introduced earlier, informally, in Stage 6).
- **CloudWatch** — reading logs, understanding what App Runner sends there
  by default. Needed the first time anything on AWS breaks, realistically
  as early as Stage 6-7.
- **DNS mechanics in practice** — TTLs, propagation, what actually happens
  when you change a record. You already understand DNS conceptually; this
  is about doing a real cutover carefully. Needed for Stage 10.
- **CORS** — why it exists, how it will matter the moment frontend and
  backend are hosted on different domains during Stages 3-7 (testing an
  AWS frontend against the still-live Render backend).

---

## I CAN LEARN THIS LATER

*(No verified requirement in the current app — revisit only if a real
feature need appears, per the plan's own reasoning for not building these
now.)*

- **Cognito** — no user accounts exist anywhere in the app today.
- **RDS / PostgreSQL** — verified zero persistence anywhere in the current
  app (`CURRENT_INFRASTRUCTURE.md` Section E); there's nothing to migrate
  and no current reason to add it.
- **Lambda + API Gateway** — genuinely well-suited to this app's stateless
  design *eventually*, but deliberately deferred past the first migration
  (see the Backend Hosting section of `AWS_MIGRATION_PLAN.md` for why) so
  you're not learning an adapter layer and cold-start behavior at the same
  time as everything else.
- **ECS/Fargate, VPCs, subnets, load balancers, security groups** — this
  app has no networking requirement that justifies this complexity today;
  it's real, valuable, advanced AWS knowledge worth learning deliberately
  later, not bundled into this migration.
- **Route 53** — no specific benefit identified over keeping GoDaddy; only
  becomes relevant if you adopt other AWS services that specifically
  integrate with it.
- **CI/CD pipelines beyond "push triggers a deploy"** — Render already
  gives you this today in its simplest form; AWS CodePipeline/CodeBuild (or
  App Runner/Amplify's own built-in equivalents) are worth learning, but
  not urgently — App Runner and Amplify both have adequate built-in
  deploy-on-push behavior without needing a hand-built pipeline first.
- **Auto-scaling configuration** — this app's traffic doesn't currently
  demand it; the default behavior of whichever service you choose is
  sufficient to start.
