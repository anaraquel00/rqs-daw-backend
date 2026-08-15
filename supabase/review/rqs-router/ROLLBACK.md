# RQS Uplink Router — Rollback Procedure

## Preconditions

- Keep `index.before.ts` unchanged.
- Do not expose any Supabase secret in Git or logs.
- Confirm database rollback completed before router rollback.

## Router rollback

1. Restore the exact source from:

   `supabase/review/rqs-router/index.before.ts`

2. Deploy it again as `rqs-router`.

3. Restore the previous function configuration.

4. Confirm:

   - `/rqs-router` health endpoint responds;
   - `flower-newworld` redirects correctly;
   - no secret appears in Edge Function logs.

## Database rollback

Execute only the reviewed:

`uplink_tracking_rollback.sql`

## Post-rollback audit

Run:

`uplink_tracking_audit.sql`

Confirm the original three-argument RPC and original ACLs are restored.