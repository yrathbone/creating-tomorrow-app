# Legacy raw-history count: read-only steps (count only, NOT RUN)

Status: NOT RUN. Claude has no database access and has not requested or handled credentials. These steps are for Jo, to run in Jo's own read-only session. Nothing here deletes or updates anything.

## Rules for the run

1. Read-only only. Start the session as read-only: `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;`
2. Run only the SELECT statements below. They return counts only.
3. Do not select answer content, row IDs, names, emails or any other personal data. None of the statements do.
4. Stop rule: if any "recent" count, any "unknown age" count, any "not array" count, or the scan "result not object" count is above zero, STOP and report the counts to Jo before any cleanup.
   A recent draft or scan may be active or in progress. An unexpected JSON shape is out of scope. A row with no recorded age is not safe to clear.
5. Record only the counts, the date and the database name. Do not record any row content.

## Why these statements are safe with unexpected JSON

Each `json_array_length` call sits inside a `CASE` branch that runs only when `json_typeof` says the value is an array. PostgreSQL evaluates a `CASE` branch only when it is reached, so `json_array_length` is never called on a scalar, null or object. A value that is not an array counts as 0 in the length expression and is caught by the "not array" column instead.

## Step 1: drafts (`resume_ingestion_drafts`, field `history`)

```sql
SELECT
  count(*) FILTER (WHERE CASE WHEN json_typeof(history) = 'array' THEN json_array_length(history) ELSE 0 END > 0)
    AS drafts_with_history,
  count(*) FILTER (WHERE CASE WHEN json_typeof(history) = 'array' THEN json_array_length(history) ELSE 0 END > 0
                     AND updated_at < now() - interval '30 days')
    AS drafts_history_inactive_30d,
  count(*) FILTER (WHERE CASE WHEN json_typeof(history) = 'array' THEN json_array_length(history) ELSE 0 END > 0
                     AND updated_at >= now() - interval '30 days')
    AS drafts_history_recent,
  count(*) FILTER (WHERE CASE WHEN json_typeof(history) = 'array' THEN json_array_length(history) ELSE 0 END > 0
                     AND updated_at IS NULL)
    AS drafts_history_unknown_age,
  count(*) FILTER (WHERE json_typeof(history) IS DISTINCT FROM 'array')
    AS drafts_history_not_array
FROM resume_ingestion_drafts;
```

## Step 2: scans (`scan_histories`, field `result_data`, key `qa_history`)

```sql
SELECT
  scan_type,
  count(*) FILTER (WHERE CASE WHEN json_typeof(result_data -> 'qa_history') = 'array'
                              THEN json_array_length(result_data -> 'qa_history') ELSE 0 END > 0)
    AS scans_with_qa,
  count(*) FILTER (WHERE CASE WHEN json_typeof(result_data -> 'qa_history') = 'array'
                              THEN json_array_length(result_data -> 'qa_history') ELSE 0 END > 0
                     AND created_at < now() - interval '30 days')
    AS scans_qa_inactive_30d,
  count(*) FILTER (WHERE CASE WHEN json_typeof(result_data -> 'qa_history') = 'array'
                              THEN json_array_length(result_data -> 'qa_history') ELSE 0 END > 0
                     AND created_at >= now() - interval '30 days')
    AS scans_qa_recent,
  count(*) FILTER (WHERE CASE WHEN json_typeof(result_data -> 'qa_history') = 'array'
                              THEN json_array_length(result_data -> 'qa_history') ELSE 0 END > 0
                     AND created_at IS NULL)
    AS scans_qa_unknown_age,
  count(*) FILTER (WHERE result_data -> 'qa_history' IS NOT NULL
                     AND json_typeof(result_data -> 'qa_history') IS DISTINCT FROM 'array')
    AS scans_qa_not_array,
  count(*) FILTER (WHERE result_data IS NULL
                     OR json_typeof(result_data) IS DISTINCT FROM 'object')
    AS scans_result_not_object
FROM scan_histories
GROUP BY scan_type;
```

Notes:
- `created_at` is the scan's creation time. Scans have no separate last-activity field, so the 30-day split uses creation time.
- `updated_at` on drafts is the last change time. Live reads do not change it.
- If `result_data` itself is NULL or is not a JSON object, `result_data -> 'qa_history'` returns NULL, so such a row would not be counted as a legacy answer. The `scans_result_not_object` column (step 2) counts these rows separately, grouped by `scan_type`, including NULL. Any non-zero value is a STOP condition, because such rows fall outside the count above.

## Step 3: what to report

Report only these numbers, by table, age bucket and scan type:
- drafts: `drafts_with_history`, `drafts_history_inactive_30d`, `drafts_history_recent`, `drafts_history_unknown_age`, `drafts_history_not_array`
- scans: `scans_with_qa`, `scans_qa_inactive_30d`, `scans_qa_recent`, `scans_qa_unknown_age`, `scans_qa_not_array`, `scans_result_not_object`, for each `scan_type`
- the date and the database name

## Decision after the count

- If `drafts_history_recent`, `drafts_history_unknown_age`, `drafts_history_not_array`, `scans_qa_recent`, `scans_qa_unknown_age`, `scans_qa_not_array` and `scans_result_not_object` are all 0:
  the remaining raw-history rows are inactive, at least 30 days old and in the expected shape. A cleanup may be considered under the separate, approved scope below.
- Otherwise: STOP. Report the counts. Do not clean up.

## Approved cleanup scope (not yet run)

Jo's approval (#7074856452): cleanup only after the count is reviewed and only if the stop rule passes. Clear only the raw fields, on records that are clearly inactive and at least 30 days old:
- `resume_ingestion_drafts.history`
- `scan_histories.result_data` key `qa_history`

Preserve every row and every other field. Before any change, report the counts and the exact proposed statements, and wait for a separate go-ahead. The cleanup statements are not written here.
