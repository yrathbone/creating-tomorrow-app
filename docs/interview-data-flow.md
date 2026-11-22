# Resume interview and job flow: where answers and transcripts go (review draft, 2026-11-22)

## 0. Status

- Branch: `voice-typed-fallback-ondevice` in `yrathbone/creating-tomorrow-app`. PR #74 is a draft.
- Relationship: the previous review point is parent `3c83316`. The current product commit is `232f81a` (job-flow change), pushed for review on top of `3c83316`. This document is committed after `232f81a`.
- Not merged. Not deployed. No staging, production, database, Render or cron action has been taken.
- Evidence for `232f81a`: branch `review/issue1-job-disposal-evidence` in `creating-tomorrow-ops`, commit `24784df`. Frontend 384 of 384 pass; backend 922 run, OK, 1 skipped (PostgreSQL modules excluded).
- Legacy-history count and cleanup: NOT RUN. See `docs/legacy-history-count-steps.md`.

## 1. Summary

- A typed or spoken answer lives in the browser page while the interview is in progress. Answers from earlier rounds stay on the page so the next question can use them.
- When the analysis produces suggested skills and experience for review (the review step), the raw answers are removed from the page. The server also stops keeping raw answer history at that point.
- Each "Send answers and continue" sends the answers so far to our server, which sends them to the AI provider (Anthropic) for analysis.
- The structured results kept for review are the pending questions and suggested facts. They are removed when the member saves, discards, or they expire.
- Nothing reaches the Career Profile until the member presses Save.
- Job comparison: after a successful tailored-resume build, the raw gap-interview answers are removed from the saved scan. A failed build keeps them so a retry is possible.
- Deleting data from our database does not delete anything the AI provider holds. The app has no mechanism to delete provider-held data. See section 4.

## 2. Resume interview, step by step

| Step | Where | What is held | Persists? |
|---|---|---|---|
| Speak or type an answer | `voiceAnswer.js` (`appendTranscript`), `resumeReview.js` textarea | The text, in the page | No: lost on page reload or navigation |
| Send answers and continue | `resumeReview.js` `submitResumeAnswers` (about line 467): `resumeState.history.push(...answered)`; POST `/api/career/resume-discover` with `history` (about line 485) | All answers so far, in page memory, then in the request body | Request body: no |
| Server receives request | `routes.py` `resume_discover` (about line 691): checks the draft is live (409 if not) before any AI call | The request | No (logs: see section 3) |
| AI analysis | `elevate.py` `discover` (line 388) builds the prompt including `history_text`; `_call_with_retry` (line 331) calls the Anthropic Messages API with model `CT_MODEL` (default `claude-sonnet-5`, `render.yaml`) | The prompt, including the answers | At the provider: see section 4 |
| Server stores an intermediate round | `routes.py` `resume_discover` after the AI call: `draft.history = []`; stores `pending_questions`, `round_number`, `categories` | Questions still to ask | Yes, in the draft row, until save, discard or expiry |
| Review step (analysis returned suggestions, stage confirm) | Server: stores `discovered_facts` (suggestions) and `history = []`. Page: `resumeReview.js` confirm branch sets `resumeState.history = []`, `currentResumeQuestions = []`, and removes the answer boxes. Suggestions are kept | Suggestions only | Yes, suggestions only, in the draft row and the page |
| Member reviews suggestions | `resumeReview.js` review card (`renderResumeReview`) | The suggested facts | In page memory and the draft |
| Member presses Save | `resumeReview.js` `resume-save-btn` handler; POST `/api/career/resume-save` | Roles and facts the member approved | Profile rows written; draft deleted; page state cleared |
| Resume the draft later | GET `/api/career/resume-draft` returns the draft; `resumeReview.js` (about line 232) restores `history`, which is empty after analysis | Structured results | Same as the draft |
| Discard | DELETE `/api/career/resume-draft` | | Draft row deleted |

Browser storage: no interview answer is written to `localStorage`, `sessionStorage` or IndexedDB. Checked by a source-text search of `resumeReview.js` and `voiceAnswer.js`. `sessionStorage` is used only for the applications view preference and sign-in tokens.

## 3. Server logs

- `llm_utils.py` `log_usage` prints token counts and the tool name only, never prompt or response content (its own docstring says so).
- `elevate.py` `_diagnose` prints a failure category only (for example `invalid_json`).
- A search of `backend/career/*.py` and `backend/*.py` found no logging of answers, history or transcripts. One unrelated `print` in `term_pipeline.py` logs counts only.
- NOT verified: request logs written by the hosting platform (Render) or any web-server access log. These are outside the repository and were not inspected.

## 4. AI provider side (Anthropic)

Sources (read 2026-11-22):
- Standard retention, Anthropic Privacy Center, "How long do you store my organization's data?": <https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-your-organizations-data> (article dated July 1, 2026).
- Data retention and zero data retention, Claude Platform Docs: <https://platform.claude.com/docs/en/build-with-claude/api-and-data-retention>.

What the standard policy says (quoted in substance):
- For Anthropic API users, inputs and outputs are automatically deleted from Anthropic's backend within 30 days of receipt or generation.
- Exceptions listed in the article: a service with longer retention under the customer's control (for example the Files API); a separate agreement (for example a zero data retention agreement); retention needed to enforce the Usage Policy; retention required by law.
- Flagged Usage Policy violations: inputs and outputs may be kept up to 2 years, and trust and safety classification scores up to 7 years. Submitted feedback is kept for 5 years. These are not our app's choices, but they are exceptions to the 30-day rule.
- Covered Models: the Platform Docs page lists models that require 30-day retention and are not available under zero data retention. The default model in our configuration, `claude-sonnet-5`, is not on that list as read.

Account-specific evidence (supplied by Jo, comments #7074518756 and #7074548479; not from Anthropic's documentation):
- The viewed organisation's Data retention setting in the Claude Console shows "On · 30 days". That indicates zero data retention is not active for that organisation.
- The app's API keys are in that workspace.
- A workspace-level override or the effective retention for the app's keys has NOT been verified. Effective retention for the app is therefore NOT fully confirmed.
- No retention setting was changed.

What our app can and cannot do:
- We can stop storing answers on our side. This is done for the resume interview and, after a successful build, for the job flow.
- We cannot delete data already held by the provider. The app has no call that deletes provider-held inputs or outputs.
- No claim is made that the provider deletes data immediately. Deletion by the provider is governed by the terms above, subject to the exceptions, and by the workspace setting once it is verified.
- Our database deletion must not be described as provider deletion.

## 5. Database (what is stored, and for how long)

Table `resume_ingestion_drafts` (`backend/models.py`):
- `history`: always empty after a successful analysis. Previously held every raw answer. Rows written before this change may still hold answers until they are next analysed, saved, discarded or expire. No purge has been performed.
- `discovered_facts`: structured suggestions. They are derived from answers, so their wording can echo an answer. Kept until save, discard or expiry, for the member to review.
- `pending_questions`, `analysis_summary`, `roles`, `education`, `certifications`, `categories`, `round_number`, `updated_at`.
- Retention (policy direction approved by Jo on 2026-11-22): 30 days from `updated_at`, with manual discard sooner. The deletion job is declared in `render.yaml` but NOT active. Live reads and writes delete an expired draft (`career/draft_retention.py`).
- Backups: Render keeps point-in-time recovery for 3 days (Hobby) or 7 days (Pro or higher) on paid Postgres. Deleted rows can exist in backups for that window. Source: <https://render.com/docs/postgresql-backups>.

Table `scan_histories` (`backend/models.py`):
- `result_data` (JSON) holds the job-comparison details. After a successful build, the `qa_history` key is removed. Scan rows created before this change may still hold `qa_history`.
- There is no time-based expiry for scan rows on this branch.

Profile rows (`Experience`, `Skill`, ...) are written only by `/resume-save`, after the member's Save.

## 6. Job-comparison flow

- `/job-discover` (`routes.py` about line 1122) sends the submitted answers to the AI and stores nothing itself. It creates no draft.
- `/job-build-resume` (`routes.py` about lines 1187-1188) saves the submitted `qa_history` into `ScanHistory.result_data["qa_history"]` before the AI call, so a failed build can be retried. The frontend restores it from the server (`jobMatch.js` about line 1474).
- CHANGED in `232f81a`: after a successful build, in the same commit as the tailored resume, the `qa_history` key is removed from the scan. The scan row, its other metadata (for example `term_plan` and match details) and the saved resume are kept. A failed build keeps the answers. A later successful build removes them.
- NOT changed: scan rows created before this change that still hold `qa_history`. A one-off cleanup needs a read-only count first and separate approval (section 9).

## 7. What the current work changes

- `routes.py` `resume_discover`: after a successful analysis, `draft.history = []`. Raw answers are not stored on the server.
- `routes.py` `job_build_resume`: after a successful build, removes only the `qa_history` key from the scan, in the same commit as the resume (`232f81a`).
- `resumeReview.js`: at the review step, clears the page's answer history and answer boxes, keeping the suggestions. After a successful save, clears the remaining page state.
- `login.html`: the disclosure says earlier questions keep answers on the page; when the analysis has produced suggestions, the answers are removed from the page and the saved draft and only the suggestions are kept. It says nothing reaches the Career Profile until Save, and makes no promise about the AI service's retention.
- Stale-draft refusals from the earlier change still apply (expired or discarded: 409, no AI call, nothing saved).

## 8. What the tests prove and do not prove

Backend, mocked AI, SQLite:
- `test_interview_transcript_disposal.py` (6 tests): after a successful analysis the saved draft holds no raw answer history; structured suggestions stay for review at the confirm stage; suggestions do not reach the Career Profile until Save; a failed analysis writes nothing and does not echo the answer; a typed answer takes the same path; Save writes profile rows and clears the draft.
- `test_job_build_qa_disposal.py` (5 tests): a successful build removes the raw answers and keeps the term plan and match details; a failed build keeps the answers for retry and does not echo them; a later successful build removes them; a build with no scan saves the resume and touches no scan; another member cannot build against, or clear, this member's answers.
- `test_draft_retention.py`: expiry, discard, sweep and the stale-draft refusals.

Frontend, `backend/tests/frontend/voice_answer.test.js`:
- SOURCE-TEXT ASSERTION: the review-step branch and the save handler contain the clearing statements; the error path does not clear the answers. These check source text, not what the page does.
- SOURCE-TEXT ASSERTION: the disclosure text has the required parts and not the old wording; `resumeReview.js` and `voiceAnswer.js` contain no browser-storage calls.

They do NOT prove:
- What the browser's memory or the page's DOM holds after the member leaves or reloads the page (not run in a browser).
- Anything about the AI provider's actual retention for our account (section 4).
- Behaviour on PostgreSQL (the PostgreSQL test modules were not run).
- Anything about the hosting platform's logs.
- That the 30-day deletion works in production (the job is not active).
- That legacy rows have been cleaned up (no cleanup has been run).

## 9. Pending and Jo actions

Pending (not run):
- Legacy-history count (read-only, count-only). Steps are in `docs/legacy-history-count-steps.md`. It needs database access that has not been provided. Claude will not connect or handle credentials.
- Legacy-history cleanup. Requires the count first, a stop-rule check, and separate approval. Nothing is deleted or updated.

Jo actions:
1. Confirm the workspace-level retention override for the app's API keys, and whether the app's effective retention is 30 days.
2. If the count is wanted, run the read-only steps in `docs/legacy-history-count-steps.md` yourself, or give Claude a read-only connection through your own process. Do not paste credentials into chat.
3. Decide whether to approve a cleanup after the count, subject to the stop rule.
4. Decide when the 30-day deletion job should be created in Render (separate approval).
5. Confirm the job-comparison retention design once the count is known.
6. Decide when the privacy notice can be published, after browser QA.
