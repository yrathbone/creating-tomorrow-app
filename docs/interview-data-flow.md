# Resume interview and job flow: where answers and transcripts go (review draft, 2026-11-22)

Branch: `voice-typed-fallback-ondevice` (PR #74, draft). Pushed for review: `1b14524..3c83316`, plus the job-flow change
committed after that. Not merged, not deployed.
Scope: the resume interview (`frontend/career/js/resumeReview.js`), the speech prototype (`voiceAnswer.js`), the server
routes that handle answers, and the job-comparison flow (section 6).

## 1. Summary

- A typed or spoken answer lives in the browser page while the interview is in progress. Answers from earlier rounds stay on the page so the next question can use them. When the analysis produces suggested skills and experience for review (the review step), the raw answers are removed from the page. They are also removed from the saved interview draft on the server, which never keeps raw history after a successful analysis.
- Each "Send answers and continue" sends the answers so far to our server, which sends them to the AI provider (Anthropic) for analysis.
- Structured results are kept for the member to review: pending questions and suggested facts. They are removed when the member saves, discards, or they expire.
- Nothing reaches the Career Profile until the member presses Save.
- Deleting data from our database does not delete anything the AI provider holds. See section 4.
- Job comparison: after a successful tailored-resume build, the raw gap-interview answers are removed from the saved scan. A failed build keeps them so a retry is possible.

## 2. Resume interview, step by step

| Step | Where | What is held | Persists? |
|---|---|---|---|
| Speak or type an answer | `voiceAnswer.js` (`appendTranscript`), `resumeReview.js` textarea | The text, in the page | No: lost on page reload or navigation |
| Send answers and continue | `resumeReview.js` `submitResumeAnswers` (about line 467): `resumeState.history.push(...answered)`; POST `/api/career/resume-discover` with `history` (about line 485) | All answers so far, in page memory, then in the request body | Request body: no |
| Server receives request | `routes.py` `resume_discover` (about line 691): checks the draft is live (409 if not) before any AI call | The request | No (logs: see section 3) |
| AI analysis | `elevate.py` `discover` (line 388) builds the prompt including `history_text`; `_call_with_retry` (line 331) calls the Anthropic Messages API with model `CT_MODEL` (default `claude-sonnet-5`, `render.yaml`) | The prompt, including the answers | At the provider: see section 4 |
| Server stores the result (intermediate round) | `routes.py` `resume_discover` after the AI call: `draft.history = []`; stores `pending_questions`, `round_number`, `categories` | Questions still to ask | Yes, in the draft row, until save, discard or expiry |
| Review step (analysis returned suggestions, stage confirm) | Server: stores `discovered_facts` (suggestions) and `history = []`. Page: `resumeReview.js` confirm branch sets `resumeState.history = []`, `currentResumeQuestions = []`, removes the answer boxes; the suggestions are kept | Suggestions only | Yes, suggestions only, in the draft row and the page |
| Member reviews suggestions | `resumeReview.js` review card (`renderResumeReview`) | The suggested facts | In page memory and the draft |
| Member presses Save | `resumeReview.js` `resume-save-btn` handler; POST `/api/career/resume-save` | Roles and facts the member approved | Profile rows written; draft deleted; page state cleared |
| Resume the draft later | GET `/api/career/resume-draft` returns the draft; `resumeReview.js` (about line 232) restores `history` (empty after analysis) | Structured results | Same as the draft |
| Discard | DELETE `/api/career/resume-draft` | | Draft row deleted |

Browser storage: no interview answer is written to `localStorage`, `sessionStorage` or IndexedDB. Checked by source-text search of
`resumeReview.js` and `voiceAnswer.js`. `sessionStorage` is used only for the applications view preference and sign-in tokens.

## 3. Server logs

- `llm_utils.py` `log_usage` prints token counts and the tool name only, never prompt or response content (its own docstring says so).
- `elevate.py` `_diagnose` prints a failure category only (for example `invalid_json`).
- A search of `backend/career/*.py` and `backend/*.py` found no logging of answers, history or transcripts. One unrelated `print` in `term_pipeline.py` logs counts only.
- NOT verified: request logs written by the hosting platform (Render) or any web-server access log. Those were not inspected. They are outside the repository.

## 4. AI provider side (Anthropic)

Source read 2026-11-22: <https://platform.claude.com/docs/en/build-with-claude/api-and-data-retention>

- Under zero data retention (ZDR), Anthropic does not store customer prompts or responses at rest after the response is returned, except where needed to comply with law or to combat misuse. ZDR is enabled per organization by Anthropic sales.
- The page says conversation content is "not retained by default", with an exception for "Covered Models", which require 30-day retention. The Covered Models named are Claude Fable 5.2, Claude Mythos 5.2, Claude Fable 5.1, Claude Mythos 5.1, Claude Fable 5 and Claude Mythos 5. The default model in our configuration, `claude-sonnet-5`, is not on that list as read. The page does not state the standard retention period for accounts outside ZDR; it refers to the commercial data retention policy, which I did not read.
- Data's review (#7074364531 and #7074585315) states that Anthropic's standard commercial documentation describes deletion of standard API inputs and outputs within 30 days, with exceptions. I have NOT verified that wording against the commercial policy.
- Account evidence supplied by Jo (comments #7074518756 and #7074548479): the viewed organization's Data retention setting is "On · 30 days", so ZDR is not active there. The app's API keys are in that workspace. A workspace-level override has NOT been checked. Effective retention for the app is therefore NOT fully confirmed.
- No retention setting was changed.

What our app can and cannot do:
- We can stop storing answers on our side (done in this change for the resume interview and, after a successful build, for the job flow).
- We cannot delete data already held by the provider. The API offers no per-message delete call that this app uses.
- Our database deletion must not be described as provider deletion, and no provider-deletion claim is made.

## 5. Database (what is stored, and for how long)

Table `resume_ingestion_drafts` (`backend/models.py`):
- `history`: always `[]` after a successful analysis. Previously held every raw answer. Rows written before this change may still hold answers until they are next analysed, saved, discarded or expire. No purge has been performed.
- `discovered_facts`: structured suggestions. They are derived from answers, so their wording can echo an answer. Kept until save, discard or expiry, for the member to review.
- `pending_questions`, `analysis_summary`, `roles`, `education`, `certifications`, `categories`, `round_number`, `updated_at`.
- Retention (policy direction approved by Jo on 2026-11-22): 30 days from `updated_at`, with manual discard sooner. The deletion job is declared in `render.yaml` but NOT active. Live reads and writes delete an expired draft (`career/draft_retention.py`).
- Backups: Render keeps point-in-time recovery for 3 days (Hobby) or 7 days (Pro or higher) on paid Postgres. Deleted rows can exist in backups for that window. Source: <https://render.com/docs/postgresql-backups>.

Profile rows (`Experience`, `Skill`, ...) are written only by `/resume-save`, after the member's Save.

## 6. Job-comparison flow

- `/job-discover` (`routes.py` about line 1122) sends the submitted answers to the AI and stores nothing itself. It creates no draft.
- `/job-build-resume` (`routes.py` about lines 1187-1188) saves the submitted `qa_history` into `ScanHistory.result_data["qa_history"]` before the AI call, so a failed build can be retried. The frontend restores it from the server (`jobMatch.js` about line 1474).
- CHANGED in this work: after a successful build, in the same commit as the tailored resume, the `qa_history` key is removed from `ScanHistory.result_data`. The scan row, its other metadata (for example `term_plan` and match details) and the saved resume are kept. A failed build keeps the answers. A later successful build removes them.
- NOT changed: scan rows created before this change that still hold `qa_history` are not cleaned up. A one-off cleanup needs a read-only count first and separate approval (section 9).
- The 30-day draft rule does not apply to scan rows.

## 7. What this work changes

- `routes.py` `resume_discover`: after a successful analysis, `draft.history = []`. Raw answers are not stored on the server.
- `routes.py` `job_build_resume`: after a successful build, remove only the `qa_history` key from the scan, in the same commit as the tailored resume.
- `resumeReview.js`: at the review step, clear the page's answer history and answer boxes, keeping the suggestions. After a successful save, clear the remaining page state.
- `login.html`: the disclosure says earlier questions keep answers on the page, and that when the analysis has produced suggestions, the answers are removed from the page and the saved draft while the suggestions are kept. It says nothing reaches the Career Profile until Save, and makes no promise about the AI service's retention.
- Stale-draft refusals from the previous change still apply (expired or discarded: 409, no AI call, nothing saved).

## 8. What the tests prove and do not prove

Backend, mocked AI, SQLite:
- `test_interview_transcript_disposal.py` (6 tests): after a successful analysis the saved draft holds no raw answer history; structured suggestions stay for review at the confirm stage; suggestions do not reach the Career Profile until Save; a failed analysis writes nothing and does not echo the answer; a typed answer takes the same path; Save writes profile rows and clears the draft.
- `test_job_build_qa_disposal.py` (5 tests): a successful build removes the raw answers and keeps the term plan and match details; a failed build keeps the answers for retry and does not echo them; a later successful build removes them; a build with no scan saves the resume and touches no scan; another member cannot build against, or clear, this member's answers.
- `test_draft_retention.py`: expiry, discard, sweep and the stale-draft refusals.

Frontend, `backend/tests/frontend/voice_answer.test.js`:
- SOURCE-TEXT ASSERTION: the review-step branch and the save handler contain the clearing statements; the error path does not clear the answers. These check source text, not what the page does.
- SOURCE-TEXT ASSERTION: the disclosure text has the required parts and no old wording; `resumeReview.js` and `voiceAnswer.js` contain no browser-storage calls.

They do NOT prove:
- What the browser's memory or the page's DOM holds after the member leaves or reloads the page (not run in a browser).
- Anything about the AI provider's retention (section 4).
- Behaviour on PostgreSQL (the PostgreSQL test modules were not run).
- Anything about the hosting platform's logs.
- That the 30-day deletion works in production (the job is not active).
- That legacy rows have been cleaned up (no cleanup has been run).

## 9. Blockers and decisions

- Legacy cleanup: a read-only count of old raw answers in `resume_ingestion_drafts.history` and `ScanHistory.result_data["qa_history"]` needs database access. Jo has not provided it. Claude will not connect or request secrets. Jo's exact read-only steps are needed before the count, and a separate approval before any clearing.
- Provider: confirm the workspace-level retention override for the app's API keys, and the standard commercial retention period. No provider-deletion claim until then.
- Render: confirm the workspace plan (recovery window) before any activation of the cron.
- Browser: a manual QA pass on a real browser is needed for page-memory and reload behaviour (see the checklist in #7074454913).
