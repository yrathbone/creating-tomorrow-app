# Architecture Learning Checklist

Priorities below are based on the ACTUAL architecture verified in
`docs/CURRENT_INFRASTRUCTURE.md` — e.g. IAM is "learn during migration"
because Lambda (the recommended backend target, updated 2026-09-22 after
App Runner closed to new customers) requires it immediately, while RDS is
"learn later" because this app verifiably doesn't use a database.

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
- **Containers / Dockerfiles, hands-on** — added 2026-09-22: wrote a real
  `Dockerfile`, built it in AWS CloudShell, pushed the image to ECR, and
  deployed it as a working ECS Express Mode service (verified via
  `/api/health`), then deleted it. This is genuine, demonstrated
  experience now, not something still ahead of you.
- **AWS service lifecycle/deprecation awareness** — added 2026-09-22:
  caught, live in the console, that AWS App Runner had stopped accepting
  new customers — a real instance of verifying against the live product
  rather than trusting a plan (even one written minutes earlier). This is
  a genuinely valuable habit, not just a lucky catch.

---

## I SHOULD LEARN THIS DURING MIGRATION

*(These map directly to Stage 2 and Stage 6-8 of
`docs/AWS_MIGRATION_PLAN.md` — you'll need them immediately, not
eventually.)*

- **AWS IAM** — users, roles, policies. Needed from Stage 2 onward; almost
  every other AWS service leans on IAM for permissions.
- **Lambda + API Gateway, and the Mangum adapter specifically** — updated
  2026-09-22 (App Runner is no longer available to new customers): how an
  existing FastAPI app adapts to Lambda's invocation model, how API
  Gateway routes requests to it, and how cold starts actually behave
  against this app's own ~15-90s AI response times. Needed for Stage 6.
- **A real CI/CD pipeline (GitHub Actions or similar)** — moved up from
  "learn later": unlike App Runner or Amplify, Lambda has no built-in
  "watch my repo and redeploy on push" behavior. Getting back to
  Render's current push-to-deploy convenience means actually building a
  small pipeline (GitHub Actions calling the AWS CLI or SAM/CDK) — needed
  for Stage 6, not an optional later refinement.
- **S3** — buckets, permissions, static website hosting. Needed for
  Stage 3 (whichever frontend option you pick).
- **CloudFront** — CDN basics, cache invalidation, origins. Needed for
  Stage 3 if you choose S3+CloudFront over Amplify.
- **AWS Systems Manager Parameter Store / Secrets Manager** — how a running
  AWS service reads a secret without it living in code. Needed for Stage 8
  (introduced earlier, informally, in Stage 6).
- **CloudWatch** — reading logs, understanding what Lambda sends there
  by default. Needed the first time anything on AWS breaks, realistically
  as early as Stage 6-7.
- **Cost governance: budget actions and resource tagging** — added
  2026-09-22, learned directly from the ECS Express Mode test-and-delete:
  a budget *alert* only emails you; a budget *action* can actually stop
  or restrict resources automatically. Tagging every resource by project
  gives real per-project cost visibility in Cost Explorer. Needed before
  any future compute experiment, not just Stage 8.
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
- **Manual ECS/Fargate with hand-configured VPCs, subnets, load balancers,
  security groups** — updated 2026-09-22: the *simplified* version of this
  (ECS Express Mode) was already tested hands-on and deleted the same
  night. The full manual version — configuring each networking piece
  yourself instead of letting Express Mode auto-provision it — remains
  real, valuable, advanced AWS knowledge worth a later, deliberate "now I
  want to learn VPCs" project, not bundled into this migration.
- **Route 53** — no specific benefit identified over keeping GoDaddy; only
  becomes relevant if you adopt other AWS services that specifically
  integrate with it.
- **Auto-scaling configuration** — this app's traffic doesn't currently
  demand it; the default behavior of whichever service you choose is
  sufficient to start.
