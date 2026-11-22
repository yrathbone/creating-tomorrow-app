# Jo's manual steps (not run by Claude)

Claude does not have, and must not receive, console or Render credentials. Section A (the console check) and the legacy count (section C) were reported by Jo; Claude did not run them. Nothing else below has been done. Do not paste any key,
password or connection string into GitHub or chat.

## A. Read-only check: workspace retention override (Anthropic Console) - REPORTED BY JO (steps kept as reference)

Status: Jo reported the organization default as Data retention On · 30 days, with API keys in this organization per Jo. Workspace override and effective per-key setting are NOT independently verified. Claude did not run these steps.

Goal: confirm the effective data-retention setting for the workspace that holds the app's API keys. Change nothing.

1. Open the Claude Console in your own browser and sign in yourself.
2. Confirm which workspace the app's API key belongs to. Look at the key's list entry in API keys. Do not copy, reveal or
   paste the key value anywhere.
3. Switch to that workspace (if the console offers workspaces).
4. Open Settings, then Privacy Controls, then Data retention. Record the value shown for this workspace. Do not edit it.
5. If the workspace shows a value different from the organisation default, record that it is an override. If it matches
   the organisation default ("On · 30 days" as previously reported), record that no override was shown.
6. Report back only: workspace name (as shown), the retention value shown, and whether an override is shown. No key values.

If you cannot find the workspace or the setting, stop and report that. Do not change any settings.

## B. Render: create the 30-day daily sweep (cron job)

Scope, stated plainly: the job runs `backend/career/draft_sweep.py`. It permanently deletes whole rows from
`resume_ingestion_drafts` where `updated_at` is null or at least 30 days old. That includes the pending questions and the
suggested facts, not only the raw answers. It prints one count line and no content. It cannot be undone from the app.

Schedule: `17 3 * * *` (03:17 UTC every day). Render cron schedules are UTC.

Before you create it, decide the code branch. The cron job runs the code from the branch you select. The cron block is on
`voice-typed-fallback-ondevice`, which is NOT merged to main. Selecting that branch means running unmerged code in production.
Preferred: merge the cron change and the sweep code to main first, under a separate decision, and select main. Do not select
the voice branch unless you accept that.

Steps (Render Dashboard, in your own session):
1. Click New, then Cron Job.
2. Connect the repository `yrathbone/creating-tomorrow-app` and choose the branch decided above.
3. Runtime: Python. Root directory: leave blank.
4. Build command: `pip install -r backend/requirements.txt`
5. Command: `cd backend && python -m career.draft_sweep`
6. Schedule: `17 3 * * *`
7. Plan: Starter (the same value as in `render.yaml`).
8. Auto-deploy: Off.
9. Environment variables: add `PYTHON_VERSION` = `3.12.10`.
10. Add `DATABASE_URL` as a secret. Paste the connection string from the Render dashboard for `creating-tomorrow-db`
    yourself. Claude never sees or handles this value. Confirm it is the production database before saving.
11. Create the cron job. Do not trigger a run yet.

Cost (source: Render cron docs, read 2026-11-22, <https://render.com/docs/cronjobs>): cron jobs are billed per second of run
time, with a minimum monthly charge of $1 per cron job service. The per-second rate for the Starter plan was not verified on
the pricing page as read, so the exact cost of this job is UNVERIFIED beyond that $1 minimum. Check the Render billing page
before creating it.

Do not change the web service, the database, or any other setting while creating this job.

## C. Legacy count and cleanup status

- The legacy-history count: run by Jo on 2026-11-22 (read-only, counts only). Recorded: 16 job-comparison scans with Q&A; 7 at least 30 days old; 9 newer than 30 days. Stop condition triggered.
- The legacy-history cleanup: BLOCKED by the stop condition. Needs the stop condition resolved, a fresh count, review of the exact statements, and separate approval of a written plan.
- PR #74 stays a draft. No merge, deploy, staging or production change.
