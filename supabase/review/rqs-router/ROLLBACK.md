# RQS Uplink Router — Safe Rollback

The rollback disables tracking while keeping public redirects available. It
must never restore the vulnerable legacy RPC or its public grants.

## Preconditions

- Confirm an approved database backup or restore point.
- Keep `index.before.ts` only as historical evidence. **Never redeploy it.**
- Confirm `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are configured.
- Do not expose secrets in Git, commands, screenshots, or logs.

## Safe order

1. Deploy `index.rollback-safe.ts` as `rqs-router`.
2. Verify the health endpoint reports `tracking: "disabled"`.
3. Verify a known Uplink returns a redirect without changing counters.
4. Run the reviewed `uplink_tracking_rollback.sql`.
5. Run `uplink_tracking_audit.sql` and confirm:
   - the V3 RPC is absent;
   - the legacy RPC is absent or has no application-role EXECUTE grants;
   - public table-wide SELECT is absent;
   - the authenticated owner-only SELECT policy remains;
   - redirect-only routing still works.

## Recovery after the incident

Fix the defect in a new reviewed migration and router revision. Do not use the
pre-migration source or ACLs as a shortcut to re-enable tracking.
