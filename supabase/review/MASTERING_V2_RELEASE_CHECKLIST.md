# Mastering V2 Project 1 — Release Checklist

All blocking items must be PASS before final merge/release.

## Completed engineering / staging gates

- [x] candidate rebuilt from current backend main with Uplink V3.2 preserved
- [x] validated Mastering V2 code ported
- [x] authenticated V2 presigned upload implemented
- [x] user-owned S3 input namespace implemented
- [x] user-owned S3 output namespace implemented
- [x] Preview excluded from Full Master quota
- [x] atomic quota migration candidate written
- [x] quota audit/test/rollback candidates written
- [x] legacy Full Master bypass retired
- [x] Node output upload changed to streaming
- [x] undeclared Supabase JS payment dependency removed
- [x] npm-generated lockfile audit fix applied
- [x] isolated Supabase staging migration PASS
- [x] staging security audit PASS
- [x] native multi-session quota concurrency PASS
- [x] authenticated staging HTTP validation PASS
- [x] frontend auth/security follow-up implemented and tested
- [x] real-audio Mastering regression PASS
- [x] isolated AWS staging provisioning PASS
- [x] production-bucket isolation from staging role PASS
- [x] exact-origin CORS PASS
- [x] real presigned S3 upload PASS
- [x] real Preview DSP PASS
- [x] real Full Master S3 → DSP → S3 PASS
- [x] real presigned master download PASS
- [x] real frontend FE → BE → S3 E2E PASS
- [x] cumulative frontend release reconciliation PR #5 created
- [x] cumulative backend release reconciliation PR #5 created
- [x] frontend release candidate mergeability PASS
- [x] backend release candidate mergeability PASS
- [x] Final Beta product mode selected: WAITLIST_ONLY
- [x] payment runtime changed to fail closed (`RQS_PAYMENT_MODE` absent → disabled)
- [x] manual Premium approval template added; UUID-authoritative and default ROLLBACK

## Must be green again on final exact candidate heads

- [ ] final exact-current-head backend CI PASS after WAITLIST_ONLY/runbook changes
- [x] frontend exact-head CI PASS on current frontend release candidate

## Review gates

- [ ] independent final code review PASS
- [ ] independent final SQL review PASS against Production Audit Before

## Production gates — NOT STARTED

- [ ] production backup / recovery point PASS
- [ ] production Audit Before PASS
- [ ] exact production backend rollback target recorded
- [ ] exact Vercel Production rollback target recorded
- [ ] explicit Production `RQS_PAYMENT_MODE=disabled` confirmed
- [ ] explicit production authorization
- [ ] reviewed Mastering V2 SQL migration applied once in Production
- [ ] Production SQL Audit After Migration PASS
- [ ] controlled backend Production validation PASS
- [ ] controlled frontend Production validation PASS
- [ ] Free 3/3 → waitlist behavior PASS in Production
- [ ] approved Premium account unlimited behavior PASS in Production
- [ ] controlled credential rotation completed
- [ ] final Production Audit After PASS
- [ ] final merge/release authorization

## Current release state

`PRODUCT_MODE: WAITLIST_ONLY`

`PAYMENT_DEFAULT: DISABLED / FAIL-CLOSED`

`STAGING_E2E: PASS`

`MERGE: HOLD`

`PRODUCTION_DEPLOY: HOLD`

`PRODUCTION_SQL: HOLD`
