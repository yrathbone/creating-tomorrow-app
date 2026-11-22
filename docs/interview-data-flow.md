# Resume interview: where answers and transcripts go (review draft, 2026-11-22)

Branch: `voice-typed-fallback-ondevice` (PR #74, draft). Local commit only until Jo approves a push.
Scope: the resume interview (`frontend/career/js/resumeReview.js`), the speech prototype (`voiceAnswer.js`), and the
server routes that handle its answers. The job-comparison flow is separate (see section 6).

## 1. Summary

- A typed or spoken answer lives in the browser page while the interview is in progress. It is removed from the page when the analysis produces suggestions (the review step), or when the member leaves the page, whichever comes first. Answers from earlier rounds stay in the page until the review step so the next round can use them.
- Each "Send answers and continue" sends all answers so far to our server, which sends them to the AI provider (Anthropic).
- After the AI analyses them, the server no longer keeps the raw answers. It keeps only the questions still to ask and
  the suggested facts for review (structured). Those are removed when the member saves, discards, or they expire.
- Nothing reaches the Career Profile until the member presses Save.
- Our deletion does not delete anything the AI provider holds. See section 4.

## 2. App side, step by step

| Step | Where | What is held | Persists? |
|---|---|---|---|
| Speak or type an answer | `voiceAnswer.js` (`appendTranscript`), `resumeReview.js` textarea | The text, in the page | No: lost on page reload or navigation |
| Send answers and continue | `resumeReview.js` `submitResumeAnswers` (about line 467): `resumeState.history.push(...answered)`; POST `/api/career/resume-discover` with `history` (about line 485) | All answers so far, in page memory, then in the request body | Request body: no |
| Server receives request | `routes.py` `resume_discover` (about line 691): checks the draft is live (409 if not), then calls the AI | The request | No (logs: see section 3) |
| AI analysis | `elevate.py` `discover` (line 388) builds the prompt including `history_text`; `_call_with_retry` (line 331) calls the Anthropic Messages API with model `CT_MODEL` (default `claude-sonnet-5`, `render.yaml`) | The prompt, including the answers | At the provider: see section 4 |
| Server stores the result | `routes.py` `resume_discover` (after the AI call): `draft.history = []`; stores `pending_questions`, `discovered_facts`, `round_number`, `categories` | Structured results only | Yes, in the draft row, until save, discard or expiry |
| Member reviews suggestions | `resumeReview.js` review card (`renderResumeReview`) | The suggested facts | In page memory and the draft |
| Member presses Save | `resumeReview.js` `resume-save-btn` handler; POST `/api/career/resume-save` | Roles and facts the member approved | Profile rows written; draft deleted |
| Review step (analysis returned suggestions, stage confirm) | `resumeReview.js` `submitResumeAnswers` confirm branch: `resumeState.history = []`, `currentResumeQuestions = []`, answer boxes removed; suggestions kept | Suggestions only | Page: suggestions only |
| Clear page memory after save | `resumeReview.js` save handler (after a successful save): `history`, `discoveredFacts`, `currentResumeQuestions` cleared; answer boxes removed | Nothing | n/a |
| Resume the draft later | GET `/api/career/resume-draft` returns the draft; `resumeReview.js` line 232 restores `history` (now empty) | Structured results | Same as the draft |
| Discard | DELETE `/api/career/resume-draft` | | Draft row deleted |

Browser storage: no interview answer is written to `localStorage`, `sessionStorage` or IndexedDB. Verified by search of
`resumeReview.js` and `voiceAnswer.js` (a test checks this). `sessionStorage` is used only for the applications view
preference and sign-in tokens, not for answers.

## 3. Server logs

- `llm_utils.py` `log_usage` prints token counts and the tool name only, never prompt or response content (its own docstring says so).
- `elevate.py` `_diagnose` prints a failure category only (for example `invalid_json`).
- A search of `backend/career/*.py` and `backend/*.py` found no logging of answers, history or transcripts. One
  unrelated `print` in `term_pipeline.py` logs counts only.
- NOT verified: request logs written by the hosting platform (Render) or any web-server access log. Those were not
  inspected. They are outside the repository.

## 4. AI provider side (Anthropic)

Source read 2026-11-22: <https://platform.claude.com/docs/en/build-with-claude/api-and-data-retention>

- Under zero data retention (ZDR), Anthropic does not store customer prompts or responses at rest after the response is returned, except where needed to comply with law or to combat misuse. ZDR is enabled per organization by Anthropic sales. We have NOT confirmed that our organization has ZDR.
- The page says conversation content is "not retained by default", with an exception for "Covered Models", which require 30-day retention. The Covered Models named are Claude Fable 5.2, Claude Mythos 5.2, Claude Fable 5.1, Claude Mythos 5.1, Claude Fable 5 and Claude Mythos 5. The default model in our configuration, `claude-sonnet-5`, is NOT on that list in the page as read.
- For standard accounts outside ZDR, the page refers to the commercial data retention policy. I did not read that policy in full, so the standard retention period for our account is UNVERIFIED.
- Anthropic's retention terms can change. This check reflects the page as read on 2026-11-22.

What our app can and cannot do:
- We can stop storing answers on our side (done in this change).
- We cannot delete data already held by the provider. The API offers no per-message delete call that this app uses.
- "We deleted it" in our database must not be described as "the provider deleted it".

## 5. Database (what is stored, and for how long)

Table `resume_ingestion_drafts` (`backend/models.py`):
- `history`: now always `[]` after a successful analysis. Previously held every raw answer. Old rows written before this change may still contain answers until they are next analysed, saved, discarded or expire.
- `discovered_facts`: structured suggestions. They are derived from answers, so their wording can echo an answer. They are kept until save, discard or expiry, for the member to review.
- `pending_questions`, `analysis_summary`, `roles`, `education`, `certifications`, `categories`, `round_number`, `updated_at`.
- Retention (proposal approved as a direction by Jo on 2026-11-22): 30 days from `updated_at`, with manual discard sooner. The deletion job is declared (`render.yaml`) but NOT active. Live reads and writes delete an expired draft (`career/draft_retention.py`).
- Backups: Render keeps point-in-time recovery for 3 days (Hobby) or 7 days (Pro or higher) on paid Postgres. Deleted rows can therefore exist in backups for that window. Source: <https://render.com/docs/postgresql-backups>.

Profile rows (`Experience`, `Skill`, ...) are written only by `/resume-save`, after the member's Save.

## 6. Job-comparison flow (separate)

CORRECTED 2026-11-22 (Data review of 48e1fdf): the job flow DOES persist answers.
- `/job-discover` (`routes.py` about line 1122) sends the submitted answers to the AI and stores nothing itself, and creates no draft.
- `/job-build-resume` (`routes.py` about line 1187-1188) saves the submitted `qa_history` into `ScanHistory.result_data["qa_history"]` before the AI call. The frontend restores it from the server (`jobMatch.js` about line 1474).
- `ScanHistory` rows have no 30-day expiry in this branch. So job-flow answers persist until the row is removed by other means. Their retention is an UNRESOLVED gap, separate from the resume draft rule.
- Changing this needs a design decision from Jo (what to keep, for how long, and whether to remove answers after the build).

## 7. What this change does

- `routes.py` `resume_discover`: after a successful analysis, `draft.history = []`. Raw answers are not stored on the server.
- `resumeReview.js`: the save handler also clears the pending questions and removes the answer boxes after a successful save.
- Stale-draft refusals from the previous change still apply (expired or discarded: 409, no AI call, nothing saved).

## 8. What the tests prove and do not prove

Backend, `backend/tests/test_interview_transcript_disposal.py` (6 tests) and `test_draft_retention.py`:
- After a successful analysis the saved draft holds no raw answer history.
- Structured suggestions remain in the draft for review (when the analysis reaches the confirm stage).
- Suggestions do not reach the Career Profile until Save.
- A failed analysis writes nothing and does not echo the answer in the error.
- A typed answer goes through the same path.
- Save is the step that writes profile rows, and it clears the draft.

Frontend, `backend/tests/frontend/voice_answer.test.js`:
- SOURCE-TEXT ASSERTION: the save handler and the review-step branch contain the clearing statements; a failed call's error path does not clear the answers. These are source-text checks, not DOM or browser behaviour tests.
- SOURCE-TEXT ASSERTION: `resumeReview.js` and `voiceAnswer.js` contain no browser-storage calls (checked in source text only).

They do NOT prove:
- What the browser's memory or the page's DOM holds after the member leaves the page (not run in a browser).
- Anything about the AI provider's retention (section 4).
- Behaviour on PostgreSQL (the PostgreSQL test modules were not run).
- Anything about the hosting platform's logs.
- That the 30-day deletion works in production (the job is not active).

## 9. Blockers and decisions

- Push approval: the code and tests are local until Jo approves a push to the review branch.
- Provider: confirm whether our Anthropic organization has ZDR, and read the standard commercial retention period. If immediate provider deletion is required, that is a blocker that needs a provider-side decision (ZDR enablement or a different arrangement).
- Render: confirm the workspace plan (recovery window) before any activation.
- Job flow: decide whether job-comparison answers need a stored design with expiry (section 6).
