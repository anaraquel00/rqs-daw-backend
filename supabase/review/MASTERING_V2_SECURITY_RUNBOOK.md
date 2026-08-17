# Mastering V2 Project 1 Security Runbook

Status: RELEASE CANDIDATE / PRODUCTION HOLD  
Product mode: **Final Beta — WAITLIST_ONLY**  
Production mutation: NONE by committing this file

## Final Beta product decision

Project 1 launches with payments disabled.

- `RQS_PAYMENT_MODE=disabled` must be explicitly configured in Production.
- Backend code also fails closed to `disabled` when the variable is absent.
- Free authenticated users receive three successful Full Masters total.
- Preview does not consume quota.
- At 3/3 the frontend keeps Preview available and shows the RQS PRO waitlist instead of Full Master.
- Internal/approved users receive `profiles.role = premium` manually.
- Premium authority is the immutable `auth.users.id / profiles.id` UUID, never a hard-coded browser email list.
- Live Stripe entitlement is out of scope for this release and requires a separate hardening/release gate.

Manual Premium approvals use:

`supabase/review/final_beta_manual_premium_approval.sql`

The template is fail-closed and runs with `ROLLBACK` by default. Email is only an operator cross-check; the UPDATE targets UUID only.

## Preconditions

1. Current backend `main` contains Uplink Tracking Security V3.2.
2. Mastering V2 DSP source matches validated release `mastering-v2-v1`.
3. Isolated AWS/Supabase/Vercel staging E2E is PASS.
4. Current frontend/backend release PRs are mergeable and exact-head CI is PASS.
5. Production logical backup and rollback path are confirmed immediately before any SQL or deploy.
6. Audit Before confirms the actual Production schema/runtime/deployment state.
7. Required server environment values exist without printing them.
8. Production `RQS_PAYMENT_MODE=disabled` is explicitly planned as part of the backend deployment.
9. Frontend sends the authenticated Supabase access token as `Authorization: Bearer <token>`.
10. Frontend uses `/mastering/v2/presigned-url`; legacy unauthenticated S3 keys are not accepted by V2 processing.
11. The legacy `/mastering/process` endpoint remains retired so it cannot bypass V2 authorization/quota.
12. No secret value is copied into chat, Git, logs or evidence artifacts.

## Staging evidence already completed

The following gates are complete and must not be repeated without new drift/regression:

- isolated Supabase staging migration/audit;
- Auth/JWT validation;
- native quota/concurrency validation;
- authenticated presigned upload;
- user-owned input/output S3 namespaces;
- exact-origin S3/backend CORS;
- silent-input DSP safety rejection;
- real Preview DSP;
- real Full Master S3 → DSP → S3;
- presigned final download;
- real browser FE → BE → S3 E2E;
- production bucket access denied from staging role;
- Production mutation during staging: NONE.

## Production deployment order — HOLD until explicit authorization

### Gate 0 — freeze exact candidates

Record exact heads of frontend PR #5 and backend PR #5 after all release CI is green. If either head changes, rerun exact-head gates before continuing.

### Gate 1 — backup + Audit Before [READ-ONLY except backup creation]

Before SQL/runtime mutation, capture/confirm:

- Production Supabase backup/recovery point;
- `mastering_v2_security_audit.sql` Audit Before output;
- production Lambda name, current image URI/digest, memory, timeout, role and Function URL;
- production Lambda environment **variable names only**, never secret values;
- production ECR current image digest/rollback target;
- production S3 bucket/policy/CORS relevant to Mastering;
- current Vercel Production deployment/rollback target;
- current frontend/backend `main` SHAs.

Any mismatch with the expected baseline is a STOP and re-audit.

### Gate 2 — Production Supabase security/quota migration

Only after backup + Audit Before PASS and explicit authorization:

1. validate the migration preflight against actual Production;
2. apply `mastering_v2_security_migration.sql` once;
3. run `mastering_v2_security_audit.sql` immediately;
4. verify profiles remain readable by their owner and browser profile writes are retired;
5. verify quota table/RPC contract exists;
6. stop before application deployment if any DB gate fails.

Rollback candidate:

`mastering_v2_security_rollback.sql`

Do not execute rollback blindly. Validate it against the Audit Before snapshot and inspect active reservations/dependencies first. Never use an unaudited `CASCADE`.

### Gate 3 — backend Production rollout

Deploy the exact approved backend candidate while preserving unrelated Production configuration.

Required Final Beta setting:

`RQS_PAYMENT_MODE=disabled`

Validation before frontend promotion:

- `/health` → 200;
- `/mastering/v2/capabilities` → 200;
- payment endpoint → `503 PAYMENT_DISABLED`;
- missing/invalid JWT → 401 on protected V2 routes;
- production Mastering storage target is correct;
- no staging Supabase/S3/Lambda target is present;
- logs contain no raw JWT/server secret;
- legacy `/mastering/process` remains retired.

If backend validation fails, stop and restore the recorded previous backend image/config before frontend rollout.

### Gate 4 — frontend Production rollout

Deploy/promote only the exact approved frontend candidate.

Verify the Production bundle points only to Production backend/Supabase and contains no staging Lambda, staging Supabase ref or localhost target.

Then smoke test:

- OAuth returns to `/app`;
- Free role and remaining quota load from server-backed profile state;
- Preview works and does not consume quota;
- successful Full Master consumes exactly one Free quota slot;
- Free 3/3 blocks Full Master and shows RQS PRO waitlist;
- approved Premium profile is not quota-limited;
- final download works.

### Gate 5 — manual internal Premium approvals

Only after the intended Google/RQS accounts have logged in and their immutable UUIDs are known:

1. resolve UUID + expected email READ-ONLY;
2. run `final_beta_manual_premium_approval.sql` with its default `ROLLBACK`;
3. verify exactly one intended UUID/result;
4. change only final `ROLLBACK` to `COMMIT` and rerun;
5. refresh the user's profile and verify `premium` behavior;
6. do not reset `completed_masters` when approving Premium.

### Gate 6 — credential rotation

Previously exposed Production credential classes still require controlled rotation.

Perform one class at a time, after WAITLIST_ONLY runtime is stable:

1. create replacement credential;
2. update only controlled consumers;
3. validate health/auth/functionality;
4. confirm old credential is no longer used;
5. revoke old credential;
6. record only credential identifier/state — never value.

Because Stripe is disabled in Final Beta, Stripe secret/webhook rotation must not be used to re-enable payment.

### Gate 7 — Audit After / release decision

Run Production Audit After and compare with Audit Before.

Required:

- expected DB objects/policies only;
- expected Lambda image/config only;
- expected Production targets only;
- payment remains disabled;
- no unexpected S3/IAM/domain change;
- no staging resource points to Production or vice versa;
- controlled smoke tests PASS.

Only then request final merge/release authorization.

## Supabase API-key compatibility

The backend supports both:

- current `sb_secret_*` server keys, sent in the `apikey` header only for admin REST/RPC calls;
- legacy JWT-based `service_role` keys, which also use `Authorization: Bearer`.

User requests always carry the user's Supabase Auth JWT in `Authorization: Bearer <user-jwt>`.
Secrets must never be printed or returned to the client.

## Rollback principles

If database migration succeeds but application validation fails:

- stop further rollout;
- do not promote frontend;
- restore the previously recorded backend image/config if backend rollout occurred;
- inspect `mastering_quota_reservations` before any DB rollback;
- use only a rollback reviewed against actual Production state;
- restore previous frontend deployment if frontend rollout occurred and smoke fails;
- preserve evidence of the failing gate without secret values.

No automatic Production rollback action is authorized by this document.
