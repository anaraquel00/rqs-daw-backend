# Uplink dedup retention source candidate

Status: **review-only source candidate**. No staging or Production database
operation is authorized by this document.

## Contract

- Job name: `rqs-uplink-dedup-retention-daily`
- Schedule: `0 3 * * *` (daily at 03:00 UTC)
- Predicate: `last_counted_at < statement_timestamp() - interval '48 hours'`
- Scope: delete only expired rows from `public.rqs_uplink_click_dedup`
- Explicitly unchanged: tracking RPC, click counters, quotas, RLS, grants and
  all application code

The daily cadence is maintenance scheduling, not a hard 48-hour deletion SLA.
A row can remain longer than 48 hours until the next successful run.

## Fail-closed deployment gate

1. Capture a fresh database backup and prove the restore procedure before any
   authorized environment change.
2. Run `uplink_dedup_retention_audit.sql` read-only before enabling anything
   and retain its output. The audit reports `PG_CRON = ABSENT` without querying
   missing cron catalogs, while still inspecting retention aggregates, indexes,
   RLS/ACL, counters and the Tracking V3 RPC.
3. Confirm the operator is the expected `postgres` migration owner.
4. Treat `PG_CRON = ABSENT` as a hard enable/availability gate. This source
   candidate does not authorize enabling pg_cron on any environment. After a
   separately authorized enablement, confirm the supported
   `cron.schedule`/`cron.unschedule` APIs and exact catalog surface exist, and
   that no job already uses the candidate name.
5. Confirm the base Uplink tables, column contract, RLS/ACL contract and exact
   opportunistic 48-hour RPC cleanup have not drifted.
6. Review `EXPLAIN` for the global timestamp-only predicate. The existing
   `(link_id, last_counted_at)` index is not assumed to serve that predicate.
   This candidate intentionally adds no speculative index. A dedicated index
   requires separate evidence and approval.
7. Apply only with `ON_ERROR_STOP=1`:

   ```text
   psql -v ON_ERROR_STOP=1 -f uplink_dedup_retention_migration.sql
   ```

8. Re-run the audit after the migration. Verify exact job metadata, active
   scheduler state, recent run status when `cron.job_run_details` is available,
   retention aggregates and unchanged counters.

Any missing object/API, unexpected policy/privilege, job-name collision,
operator mismatch or RPC drift is a hard STOP.

## Validation

- Insert controlled old and fresh salted-hash fixtures for at least two
  different links only in an authorized non-Production test environment.
- Execute the exact command stored in `cron.job`.
- Prove old rows for both links are removed and fresh rows for both links are
  retained.
- Prove Uplink/profile counters, quotas, ownership, RPC definition, indexes and
  ACL/RLS are unchanged.
- Wait for a scheduled execution and confirm its status through
  `cron.job_run_details` before any release decision.

Never record fingerprint values in audit evidence. Store only aggregate counts
and timestamps.

## Rollback

Rollback unschedules only the exact validated job through the supported
`cron.unschedule(text)` API:

```text
psql -v ON_ERROR_STOP=1 -f uplink_dedup_retention_rollback.sql
```

It does not recreate rows already deleted by a successful job. Recovery of
deleted rows requires the pre-deployment backup/restore anchor. Do not edit
`cron.job` directly.

## Operational follow-up

- Alert on failed or missing daily executions.
- Monitor expired-row count and relation size.
- Monitor `cron.job_run_details` growth separately; changing its retention is
  outside this candidate.
- Re-evaluate a timestamp-only partial/dedicated index only if plan and scale
  evidence justify its write and maintenance cost.
