# RQS Uplink Tracking V3.2 — Controlled Deployment Runbook

This package is review-only. A Git push must not deploy the Supabase function or
run SQL automatically.

## Required approval gates

1. Read-only audit reviewed and saved.
2. Database backup/restore point confirmed.
3. Cloudflare/Git integration classified as preview-only or disabled for this
   review branch.
4. A high-entropy `UPLINK_TRACKING_SALT` of at least 32 characters configured
   as an Edge Function secret.
5. The production router is reachable only through the Supabase Edge Functions
   edge gateway. Direct/self-hosted Deno entry paths are unsupported for
   tracking because they do not provide the trusted address-header invariant.
6. Router type-check and unit tests pass.
7. Migration and rollback reviewed by two people.

## Safe deployment order

1. Capture BEFORE snapshots using `uplink_tracking_audit.sql`.
2. Deploy the V3.2 `rqs-router` first.
   - Before the SQL migration, its V3.2 RPC call will fail safely.
   - Lookup and redirect continue through the server-side service-role client.
3. Verify health and one redirect without expecting a counter change.
   - Confirm the Supabase Edge Function receives `cf-connecting-ip`.
   - In a non-production validation environment, send two otherwise identical
     requests from one client while supplying different fake
     `cf-connecting-ip` values. Confirm the gateway overwrites them and the
     rolling 60-second rule counts at most one request.
   - Confirm the response contains `Cache-Control: no-store, private`.
4. Execute `uplink_tracking_migration.sql` once.
5. Execute `uplink_tracking_tests.sql`; it must finish with `ROLLBACK` and no
   exception.
6. Run a multi-session quota concurrency test in staging: configure exactly one
   remaining Free click, send at least five distinct fingerprints concurrently,
   and confirm exactly one increment.
7. Perform one controlled production request:
   `Instagram → /flower-newworld?src=instagram → router → RPC → Spotify`.
8. Confirm `clicks +1`, `source_instagram +1`, other sources unchanged,
   `monthly_clicks +1`, successful redirect and clean structured logs.
9. Run and save the AFTER audit.

## Safe rollback trigger

If lookup, redirect, quota, ACL or counter validation fails:

1. deploy `rqs-router/index.rollback-safe.ts`;
2. verify redirect-only operation;
3. execute `uplink_tracking_rollback.sql`;
4. run the audit again.

Never deploy `index.before.ts` and never restore the legacy public RPC grants.

## Dashboard boundary

The Analytics dashboard currently requires a separate frontend review. Do not
claim dashboard completion until its data source is proven to be Supabase rather
than `localStorage` or stale cache.
