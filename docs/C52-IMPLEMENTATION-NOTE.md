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
