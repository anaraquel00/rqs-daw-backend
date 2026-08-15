# RQS Uplink Tracking V3 — Independent Pre-Review

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
   - Fingerprints accept only `cf-connecting-ip` or `x-real-ip`.
   - Raw `x-forwarded-for` is ignored to prevent easy deduplication bypass.

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
     Instagram attribution, fingerprint shape, HEAD behavior and redirect after
     tracking failure.

8. **No automated PR validation**
   - Added a read-only GitHub Actions workflow for Deno, SQL parsing, Node
     syntax, dependency installation and high-severity audit.

## Local validation

- Deno type-check: PASS.
- Deno tests: 9 passed, 0 failed.
- Deno format: PASS.
- Four PostgreSQL review scripts parsed successfully with `pglast 8.4`.
- JavaScript syntax: PASS.
- `npm ci --ignore-scripts`: PASS.
- `npm audit --audit-level=high`: PASS threshold; one pre-existing low-severity
  `body-parser` advisory remains outside this package.
- `git diff --check`: PASS.

## Remaining approval and production evidence

- Confirm `cf-connecting-ip` or `x-real-ip` is present in the deployed Edge
  Function request.
- Confirm an approved database backup or restore point.
- Review the migration and rollback with a second person.
- Run the documented multi-session quota test in staging.
- Perform only one controlled Instagram production click after approval.
- Verify the Analytics dashboard data source separately; frontend
  `localStorage` remains outside this package.
