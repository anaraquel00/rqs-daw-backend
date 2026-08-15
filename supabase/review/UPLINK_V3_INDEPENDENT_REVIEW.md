# RQS Uplink Tracking V3.2 — Independent Pre-Review

This review was performed without production access and without executing the
migration, rollback, Edge Function deployment or a real click.

## Findings fixed before human review

1. **RLS policy drift**
   - Migration now fails closed unless RLS is enabled and the confirmed BEFORE
     public SELECT policy is the only existing SELECT policy.
   - Post-migration tests require exactly one owner-only SELECT policy.

2. **Owner consistency during tracking**
   - The RPC locks the Uplink row with `FOR NO KEY UPDATE` while resolving its
     owner so link ownership cannot change during the counter transaction.

3. **Caller-controlled address headers**
   - Fingerprints accept only `cf-connecting-ip` on the supported Supabase Edge
     gateway path.
   - Generic `x-real-ip` and `x-forwarded-for` are ignored to prevent easy
     deduplication bypass.

4. **Weak fingerprint salt**
   - Tracking fails closed when `UPLINK_TRACKING_SALT` is missing or shorter
     than 32 characters. Redirect remains available.

5. **Cached redirects bypassing analytics**
   - Active and rollback routers return temporary redirects with
     `Cache-Control: no-store, private`, `Pragma: no-cache` and
     `Referrer-Policy: no-referrer`.

6. **False source classification**
   - Referer detection now parses and verifies the hostname instead of matching
     platform names anywhere in the full URL.

7. **Insufficient router-level tests**
   - Added a mocked Supabase integration test covering lookup, RPC arguments,
     Instagram attribution, fingerprint shape, HEAD behavior, RPC success,
     deduplication (`false`) and redirect after tracking/quota failure.

8. **Calendar-minute deduplication boundary**
   - Replaced `date_trunc('minute', ...)` buckets with an atomic conditional
     upsert against the last accepted click timestamp.
   - Identical link/fingerprint requests are now rejected for a true rolling
     60 seconds, including across wall-clock minute boundaries.

9. **No automated PR validation**
   - Added a read-only GitHub Actions workflow for Deno, SQL parsing, Node
     syntax, dependency installation and high-severity audit.
   - The workflow creates an ephemeral PostgreSQL 16 service, builds a minimal
     AUDIT BEFORE fixture, and executes the migration plus transaction-wrapped
     post-migration tests without contacting Supabase.

## Local validation

- Deno type-check: PASS.
- Deno tests: 9 passed, 0 failed.
- Deno format: PASS.
- Five PostgreSQL review scripts, including the CI fixture, parsed successfully
  with `pglast 8.4`.
- JavaScript syntax: PASS.
- `npm ci --ignore-scripts`: PASS.
- `npm audit --audit-level=high`: PASS threshold; one pre-existing low-severity
  `body-parser` advisory remains outside this package.
- `git diff --check`: PASS.

## Remaining approval and production evidence

- Confirm `cf-connecting-ip` is present and overwritten by the deployed
  Supabase Edge gateway.
- Confirm an approved database backup or restore point.
- Review the migration and rollback with a second person.
- Run the documented multi-session quota test in staging.
- Perform only one controlled Instagram production click after approval.
- Verify the Analytics dashboard data source separately; frontend
  `localStorage` remains outside this package.
