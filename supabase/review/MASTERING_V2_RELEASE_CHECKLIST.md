# Mastering V2 Project 1 — Release Checklist

All blocking items must be PASS before merge/release.

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
- [ ] exact-current-head CI PASS
- [ ] independent code review PASS
- [ ] independent SQL review PASS
- [ ] isolated staging migration PASS
- [ ] staging security audit PASS
- [ ] native multi-session quota concurrency PASS
- [ ] authenticated staging HTTP validation PASS
- [ ] frontend PR #2 final decision / actual production baseline verified
- [ ] frontend auth follow-up implemented and tested
- [ ] real-audio Mastering regression PASS
- [ ] production backup PASS
- [ ] production Audit Before PASS
- [ ] explicit production authorization
- [ ] reviewed SQL migration applied once in production
- [ ] controlled production HTTP validation PASS
- [ ] production Audit After PASS
- [ ] final merge authorization

Current release state:

`MERGE: HOLD`

`PRODUCTION_DEPLOY: HOLD`

`PRODUCTION_SQL: HOLD`
