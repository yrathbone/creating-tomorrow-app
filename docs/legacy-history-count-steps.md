# Legacy raw-history count: read-only steps (count only, NOT RUN)

Status: NOT RUN. Claude has no database access and has not requested or handled credentials. These steps are for Jo, or for a
read-only session Jo opens through Jo's own process. Nothing here deletes or updates anything.

## Rules for the run

1. Read-only only. Use a read-only role or a session set to read-only (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;`).
2. Run only the SELECT statements below. They return counts only.
3. Do not select answer content, row IDs, names, emails or any other personal data. None of the statements do.
4. Stop rule: if the "recent" or "not array" counts are above zero, STOP. Report the counts to Jo before any cleanup.
   A recent draft or scan is treated as possibly active or in progress. An unexpected JSON shape is treated as out of scope.
5. Record the counts, the date and the database name only. Do not record any row content.

## Step 1: drafts (`resume_ingestion_drafts`)

```sql
SELECT
  count(*) FILTER (WHERE json_typeof(history) = 'array' AND json_array_length(history) > 0)                              AS drafts_with_history,
  count(*) FILTER (WHERE json_typeof(history) = 'array' AND json_array_length(history) > 0
                     AND updated_at < now() - interval '30 days')                                                        AS drafts_history_inactive_30d,
  count(*) FILTER (WHERE json_typeof(history) = 'array' AND json_array_length(history) > 0
                     AND updated_at >= now() - interval '30 days')                                                       AS drafts_history_recent,
  count(*) FILTER (WHERE json_typeof(history) IS DISTINCT FROM 'array')                                                  AS drafts_history_not_array
FROM resume_ingestion_drafts;
```

## Step 2: scans (`scan_histories`, field `result_data`)

```sql
SELECT
  scan_type,
  count(*) FILTER (WHERE json_typeof(result_data->'qa_history') = 'array'
                     AND json_array_length(result_data->'qa_history') > 0)                                               AS scans_with_qa,
  count(*) FILTER (WHERE json_typeof(result_data->'qa_history') = 'array'
                     AND json_array_length(result_data->'qa_history') > 0
                     AND created_at < now() - interval '30 days')                                                        AS scans_qa_inactive_30d,
  count(*) FILTER (WHERE json_typeof(result_data->'qa_history') = 'array'
                     AND json_array_length(result_data->'qa_history') > 0
                     AND created_at >= now() - interval '30 days')                                                       AS scans_qa_recent,
  count(*) FILTER (WHERE result_data->'qa_history' IS NOT NULL
                     AND json_typeof(result_data->'qa_history') IS DISTINCT FROM 'array')                                AS scans_qa_not_array
FROM scan_histories
GROUP BY scan_type;
```

Note: `created_at` is the scan's creation time. The record has no separate "last activity" field, so the 30-day split uses
creation time. A scan created within the last 30 days is counted as recent and stops the run.

## Step 3: what to report

Report only these numbers, by table and by age bucket:
- drafts: `drafts_with_history`, `drafts_history_inactive_30d`, `drafts_history_recent`, `drafts_history_not_array`
- scans: `scans_with_qa`, `scans_qa_inactive_30d`, `scans_qa_recent`, `scans_qa_not_array`, for each `scan_type`
- the date and the database name

## Decision after the count

- If `drafts_history_recent` = 0, `drafts_history_not_array` = 0, `scans_qa_recent` = 0 and `scans_qa_not_array` = 0:
  the remaining rows are inactive and in the expected shape. A cleanup could be considered, but it needs separate approval and
  its own written steps. It is NOT approved by this document.
- Otherwise: STOP. Report the counts. Do not clean up.

Cleanup is NOT described here. It needs a separate written plan and approval.
