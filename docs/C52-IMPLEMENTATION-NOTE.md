# C-52 MVP-0: implementation note (decisions before coding)

Branch `c52-my-opportunities-mvp0`, started from `origin/main` at `1ef27b5`. The feature switch `CT_OPPORTUNITIES_ENABLED` is off by default. No migration is applied, nothing is pushed, merged or deployed.

## 1. What "applied" means if the linked application is later deleted
- The opportunity stores `state` and `application_id`. "Applied" is true only when `application_id` points to an existing application row.
- The existing `applications` table is not changed. Its delete route is not changed. When an application is deleted, the foreign key sets `application_id` to NULL (`ON DELETE SET NULL`).
- Reads derive the effective state at display time: stored state `applied` with no existing application shows as **saved**, with the flag `application_removed: true` so the member sees why. Stored data is not rewritten on read.
- The member can then record the application again (section 2) or mark it dismissed. Nothing is deleted automatically.
- Tests cover both a deleted application (with and without the foreign-key rule enforced) and a re-recorded one.

## 2. Making "record application" safe to retry
Recording an application happens in one database transaction:
1. Lock the opportunity row (`SELECT … FOR UPDATE`; a no-op on SQLite in tests).
2. If the opportunity already links to an existing application, return that application and do nothing else. A retry or a double tap therefore cannot create a second tracker entry.
3. Otherwise validate the fields with the **existing** `_validated_application_fields` helper (it only reads), add the application, flush to get its id, set `application_id` and `state = applied` on the opportunity, and commit once.
4. Any error before the commit rolls the whole transaction back: no application row and no link can be left behind. There is no partial state.

Result: retries are idempotent; a partial failure leaves no unlinked application; no change to existing application data.

## 3. Scope check (per the request)
- No change to existing application data or behaviour. The only edits to existing code are the export list, the account-deletion list (both in `career/routes.py`), and one router line in `main.py`.
- If a résumé approval no longer matches the résumé (see section 4), recording the application is refused with a clear message, rather than silently recording it without the approved version.

## 4. Other design points (from the revision-2 specification)
- **Résumé approval:** the opportunity stores the approved version id and a SHA-256 of that version's data at approval. Any later change to the version changes the hash, so the approval reads as "changed since approval". This clears approval without touching the existing résumé routes.
- **Job context:** `opportunity_id` is the only identifier passed through the flow.
- **Dedupe key:** SHA-256 of the normalized https URL (lowercase host, trailing slash removed, tracking parameters removed, fragment dropped). Unique per member.
- **Limits:** 200 saved links per member; URL rules as in the specification.

## 5. Not in this change (stated)
- **Frontend screens are NOT implemented in this commit.** The tile, the saved list, the add form, the compare integration (passing opportunity_id through the existing compare, build, review and download screens), the résumé approval control and the tracker link are the next increment. The backend routes are complete and tested; the tile would stay hidden while the switch is off.
- The privacy page is not edited (held for separate review).
- Voice, notifications, discovery, scraping, automated applications and new AI calls are not added.

## Scope status against spec revision 2 (2026-11-10)

This branch is a SMALLER SLICE than MVP-0. It must not be described as all of C-52 MVP-0.

| Spec item | Backend | Frontend (this branch) |
|---|---|---|
| 1 Save a job link with member-typed details | Done | Done, except employment type is not in the form |
| 2 Verify on employer site, record date checked | Field stored (`last_verified_on`) | Not in UI |
| 3 Dismiss, restore, delete; report suspicious link | Dismiss/restore via PUT, delete, clear dismissed | Remove only. Dismiss, restore and report not in UI |
| 4 Compare with profile (existing compare screen) | Not built here (existing routes not wired to saved links) | Not in UI |
| 5 Build and approve résumé for this job | Approval stored with fingerprint; not wired to the builder UI | Not in UI |
| 6 Download approved version as DOCX | Not wired | Not in UI |
| 7 Open employer link in a new tab | Stored https link | Done (https only, no credentials, noopener noreferrer nofollow) |
| 8 Record application in tracker, with follow-up | `record-application` route (transactional) | Not in UI |
| Tile with a count of saved links | n/a | Card only, no count; sits in the profile step |
| Saved screen: source, dates added and checked, state | Source label and dates returned | Title, employer, state, location, link, pay, notice only |
| Safety notice on Saved and Add screens | Returned by API | Shown on both (fixed 2026-11-10) |
| Export includes approvals and follow-up dates; deletion includes all | Done, approval fingerprint now exported | n/a |

Backend routes that the frontend does not call yet: PUT, dismiss filter, record-application. They are covered by backend tests and need the route-authorization review before any UI uses them.

## Rev 3 (2026-11-10): URL validation and route authorization review

URL rule (backend and frontend, kept the same): a host is refused when its last label is decimal, octal or hex
(`[0-9]+`, `0x…`, case-insensitive). Browsers read such a host as an IPv4 address in another notation, so
`0x7f.0x0.0x0.0x1`, `0x7f.1`, `192.168.0x1.0x1` and `0x0a000001` are refused. Trailing dots, empty labels, local and
private suffixes and IP literals were already refused in rev 2.

Authorization review of PUT, the dismissed-clear filter and record-application:

| Route | Finding | Action |
|---|---|---|
| `PUT /opportunities/{id}` | Read the link without a row lock, so it could interleave with record-application (lost update: a link could read "saved" while an application row exists). | Fixed: the row is locked (`FOR UPDATE`). Test checks the lock on PUT and record-application. |
| `PUT` | Approval can be changed after the link is marked applied. The application keeps the résumé it was recorded with, so the link and the application can disagree about which version was used. | Reported, not changed (behaviour change; needs Data's decision). Suggested: refuse approval changes once applied. |
| `DELETE /opportunities?state=dismissed` | Scoped to the member's profile. Test shows another member's call clears only their own dismissed links. | No change. Test added. |
| `POST …/record-application` | Owned lookup with lock; approval checked against the same profile; application created in one transaction. | Fixed: the application date is now checked against the real calendar (2026-02-31 was accepted before). Test added. |
| All routes | Cross-member access returns 404 (existing test), and no request body sets an owner. | No change. |

Still open (environment-dependent): PostgreSQL row locking and the concurrent cap test; migration 0010 apply and rollback
on an empty database; the signed-in browser check.

## Rev 4 (2026-11-10): résumé consistency after application

Once an application is recorded for a link, its approved résumé version is fixed. A PUT that clears the approval, replaces it
with another version, or adds an approval to a link with none is refused with 409 while the linked application still exists.
Unrelated details (title, notes, follow-up date and the rest) stay editable. The application keeps the résumé version it was
recorded with, and the link shows that same approval.

If the linked application has been deleted, the check no longer applies, so the link can be approved again and recorded again.

Tests: clearing and replacing the approval after recording are refused and the application keeps the original version;
unrelated edits succeed; adding an approval after recording is refused. Negative control: disabling the check makes two of the
new tests fail.

Still open (environment-dependent): PostgreSQL concurrency and migration checks; the signed-in browser check.

## Rev 5 (2026-11-10): saved link connected to the comparison flow

Complete in this increment:
- "Compare this job" on a saved link opens the existing job card with the link's title and employer shown above the paste
  box. The member pastes the posting text; the app never fetches the link.
- The existing compare, question, keyword, build, review and download steps run unchanged. Nothing new is sent to the AI
  service, and no new backend route is added.
- Approval control after a résumé is built: "Approve this résumé for this saved job". It sends the existing PUT for the saved
  link, with every current field sent back unchanged and the approved version added. The backend's ownership check and
  one-version-per-link rule apply, and a recorded application blocks approval changes (rev 4).
- The saved link shows whether its approved résumé is current, changed since approval, or removed.
- "Add a job" clears any saved-link context, so a plain comparison is never attached to a link by accident.

Still tracked, not in this increment:
- Saved-link tile count and list enhancements beyond the current card.
- DOCX download from the saved-link list (the existing download button in the build step still works, and it is not linked to the saved link).
- Tracker UI for recording an application (route exists; no button).
- Dismiss, restore and report controls in the UI.
- Comparison that reuses the saved link's own history (each comparison starts from the pasted text).

Checks still open: PostgreSQL concurrency and migration 0010 apply and rollback; the signed-in browser check (the new compare and
approval controls need it to be exercised in a real session).

## Rev 6 (2026-11-10): approval is narrow; comparison starts clean

Supersedes the rev 5 statement that approval uses the full PUT. PUT replaces every field, so a dashboard copy loaded before an
edit could overwrite newer details when approval was recorded.

- New route `PUT /api/career/opportunities/{id}/approval` with body `{approved_resume_version_id}` only. It changes the approval
  and nothing else. The row is locked; ownership is checked; another member's résumé is refused (400); a recorded application
  blocks any change (409). Clearing the approval (null) is allowed while no application is recorded.
- The frontend approval sends only the version id. Test: the link is edited after the list loads, then approval is set from the
  old copy; the newer notes, title and pay are intact.
- Starting a comparison from a saved link calls the existing reset first, so the pasted posting, match report, build output and
  prior résumé id are cleared before the new saved link is attached. A plain "Add a job" also clears the link context.
  Tests run the real `jobMatch.js` in a VM; a negative control (reset removed) fails the test.

Still open (environment-dependent): PostgreSQL concurrency and migration 0010; the signed-in browser check.

## Verification status (2026-11-10): PostgreSQL and migration

PostgreSQL: BLOCKED. No PostgreSQL service, no listener on localhost port 5432, and no psql, pg_ctl, initdb or docker on this
machine. Nothing was installed and no account or database configuration was changed. The concurrency checks below are NOT run.

Migration 0010, checked on a scratch SQLite file only (not PostgreSQL, not any member or production database):
- Upgrade 0009 to 0010 creates the `opportunities` table; its 23 columns match the model exactly.
- Downgrade 0010 to 0009 removes the table; the database is back at 0009.
This does not prove PostgreSQL behaviour for the migration (types, foreign-key actions, the unique constraint).

Setup needed to run the PostgreSQL checks (for the owner to approve and provide):
1. A disposable PostgreSQL 16 instance on localhost, created for this test only, with an empty database (name suggestion: ct_c52_test)
   and a role used only for it. Its password is supplied at run time and not written to any file.
2. Set DATABASE_URL for that one shell only, pointing at that database. Never reuse a value from Render or from any member database.
3. From backend/: run `alembic upgrade 0009`, then `alembic upgrade 0010`, then `alembic downgrade 0009`, and record the output.
4. Concurrency checks to run against that database (not yet written as tests):
   a. 200-link cap: seed 199 links for one member; run 10 simultaneous creates; expect exactly one 200 and nine 409, and 200 rows.
   b. Concurrent edit and approve and record on the same link: expect one application row, a consistent state, and the
      approval and application agreeing on the résumé version.
   c. Cross-member isolation under concurrency: two members, interleaved requests; no row changes owner.
5. Afterwards: drop the database and role, and record that cleanup was done.

Signed-in browser check: still open.

## Rev 8 (2026-11-10): PostgreSQL checks run on a disposable local database

Environment: PostgreSQL 16.15 Windows x64 binaries (zip) extracted to a scratch folder, no Windows service, no administrator
rights. Cluster listening on 127.0.0.1 only, port 55432, database ct_c52_test, a separate role with a generated password.
Synthetic data only. No production or member database was used. Feature switch off. Migration 0010 not applied anywhere else.

Archive verification: SHA-256 of the local file 43BB45F173A6F08CF1D29A97A6D8DEB119E8E8093A24C00D2D1001A0CCAA8281 matches the
value posted in EnterpriseDB/edb-installers issue 731. Caveat: the value was posted by a community contributor account; the
issue does not show the value as EDB's own publication. Operator (Data) asserted the EDB publication. Recorded for review.

Results (evidence in the rev 8 package, pg-evidence/):
- Migration 0010 on PostgreSQL: upgrade 0009->0010, downgrade 0010->0009, upgrade again: all exit 0.
- T1 200-link cap, 199 seeded + 10 simultaneous creates: 1 x 200, 9 x 409, 200 rows. PASS (3 repeated runs and 2 more).
- T2 duplicate link, 10 simultaneous saves: 1 x 200, 9 x 409, 1 row. PASS.
- T3 concurrent edit, approval and recording on one link (4 each): no 500s; exactly one application; link and application agree
  on the résumé version. PASS. Interleaving varied between runs (approval first or after recording).
- T4 row lock: a create blocked by another transaction holding the member's profile row (FOR UPDATE) waited about 2 seconds and
  then succeeded. PASS. (A direct lock test on the link row for PUT and approval is not written; the code takes the same lock.)
- T5 cross-member isolation under concurrency: 20 link-targeted calls by the other member all returned 404; the owner's link
  kept its owner, with no approval or application set by the other member. PASS.
- Negative controls: with the cap lock removed and the race window widened (test-only 0.5 s pause after the real count), T1 FAILS
  with 204 rows. With the lock present, T1 passes. The unwidened first version did not discriminate, and the note records that.

Cleanup: cluster stopped (fast shutdown); data directory, extracted binaries, password files and the database role were removed
with the scratch folder (no superuser password was kept, so the role and database were removed with the cluster rather than by
DROP statements). Evidence logs kept in the rev 8 package.

Still open: the signed-in browser check. C-52 remains on HOLD pending Data's review of this evidence.

## Closeout corrections (2026-11-11)

Scope: the authorised fixes only. Feature switch CT_OPPORTUNITIES_ENABLED stays OFF by default. No migration change, no new table or column.

- **Recorded résumé reference (F01).** An application recorded from a saved job keeps the résumé it was recorded with. The tracker route `PUT /api/career/applications/{id}` refuses any change to its résumé reference, including clearing it (409). Suggestion apply, suggestion undo and deletion are refused for a résumé version that such an application uses (409). Unrelated fields stay editable, legacy applications without a saved job are unchanged, and the application's link to its saved job is kept. Deleting the application in the tracker is still allowed and shows the saved job with a flag, as before.
- **Approval includes layout (F02).** The approval fingerprint covers the résumé content and the saved layout, and a fixed renderer tag (`RENDER_FINGERPRINT`). A layout change reads as "changed since approval" and recording is refused until the résumé is approved again. Unrelated profile settings do not affect the approval. Not covered: the `ats_mode` and `template` options on download (a different file, not approved), document timestamps, and renderer changes that are not accompanied by a bump of `RENDER_FINGERPRINT`.
- **Approval is set only by its own route (F04 correction).** A details edit never changes or clears an approval. Recording an application requires a current approval.
- **Saved-link context survives refresh.** A comparison started from a saved link stores the link id with the comparison (`opportunity_id`). Recording an application for that comparison must go through the saved-link route; the tracker route refuses it with 409.
- **URL identity (F03).** `src` and `refid` are kept (they can identify a posting). Fragments are ignored for duplicates but the submitted link is stored and opened as typed. Unicode and percent-encoded host names are refused with: "This web address isn’t supported yet. Please enter a standard HTTPS job link." Punycode host names are accepted.
- **Frontend.** The saved-links card gained: check that the posting is still open (date saved), follow-up date (a date to remember; no reminders), dismiss with a reason, restore, report a suspicious link (dismisses with "looks suspicious"), show or remove dismissed links. Layout is in `opportunities.css`.
