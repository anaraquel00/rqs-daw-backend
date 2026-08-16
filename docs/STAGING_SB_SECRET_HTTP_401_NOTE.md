# Staging `sb_secret_*` HTTP 401 note

During the isolated Mastering V2 staging quota HTTP validation, the first run with a modern Supabase `sb_secret_*` key reached real JWT acquisition but admin REST calls returned HTTP 401 before the test preflight.

The staging database was checked immediately after the failed run:
- disposable profile remained `free`
- `completed_masters` remained `0`
- no quota reservations existed

Root cause: modern Supabase secret keys intentionally return HTTP 401 when the request looks browser-originated. PowerShell `Invoke-WebRequest` can use a browser-like default User-Agent even though the validator is a backend test.

Mitigation added:
- `scripts/Test-MasteringV2StagingQuotaHttpSbSecret.ps1`
- forces `Invoke-WebRequest:UserAgent` to `rqs-mastering-v2-staging-validator/1.0`
- executes the existing quota validator in the same PowerShell process
- does not print or store the staging secret
- CI validates the wrapper syntax, isolation markers and User-Agent override

This is a test-client compatibility issue, not a quota migration failure and not a production change.
