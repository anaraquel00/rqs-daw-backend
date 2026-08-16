# Project 1 — Production Smoke & Coordinated Rollback Runbook

Status: **PREPARED / PRODUCTION HOLD**

This runbook is a release contract, not authorization to deploy. Project 1 has no safe partial release order. Frontend, Mastering V2 backend and server-authorized profile/quota authority form one logical cutover unit.

## Non-negotiable release rule

Never expose production to any of these intermediate states:

```text
new backend + old frontend
new secure frontend + old backend
new profile/quota SQL + old client-authorized frontend
```

The approved release candidate must be a reconciled compatible set:

```text
SECURE FRONTEND
+
MASTERING V2 BACKEND
+
SERVER-AUTHORIZED PROFILE/QUOTA CONTRACT
```

## Required gates before production authorization

All items must be explicit PASS, not assumed:

1. final AWS/Vercel Deployment Map captured;
2. isolated staging Lambda + dedicated staging bucket + restricted staging role;
3. staging role has **zero** production-bucket permission;
4. protected Vercel Preview builds with `npm run build:staging`;
5. isolated staging FE -> BE -> S3 E2E PASS;
6. browser network isolation proves no production refs from staging;
7. frontend PR #2/#3 reconciled into one secure final candidate;
8. exact-head frontend and backend CI PASS on the final candidate;
9. profile-write compatibility PASS;
10. payment decision recorded: `WAITLIST_ONLY` or `LIVE_PAYMENT`;
11. exposed Stripe/Supabase credential remediation plan is approved and rotation is ready;
12. fresh production backup / recovery point captured;
13. production Audit Before PASS;
14. previous production Vercel deployment ID captured;
15. previous production backend ECR digest and Lambda configuration captured;
16. SQL rollback preconditions verified;
17. explicit production rollout authorization recorded.

If any item is OPEN, production remains HOLD.

## Immutable rollback evidence to capture immediately before cutover

```text
CUTOVER_TIMESTAMP=
FRONTEND_FINAL_GIT_HEAD=
FRONTEND_CANDIDATE_DEPLOYMENT_ID=
FRONTEND_PREVIOUS_PRODUCTION_DEPLOYMENT_ID=

BACKEND_FINAL_GIT_HEAD=
BACKEND_CANDIDATE_ECR_DIGEST=
BACKEND_PREVIOUS_ECR_DIGEST=
BACKEND_LAMBDA_NAME=rqs-daw-backend
BACKEND_PREVIOUS_CONFIG_SNAPSHOT=

DB_BACKUP_OR_RECOVERY_POINT=
DB_AUDIT_BEFORE_ARTIFACT=
DB_MIGRATION_SHA256=
DB_ROLLBACK_SHA256=

PAYMENT_MODE_DECISION=
CREDENTIAL_ROTATION_STATE=
```

Do not place secret values in this evidence.

## Cutover strategy selection

The final Vercel map determines which path is legal.

### Path A — validated candidate + manual promotion available

Preferred when Vercel can keep a fully validated candidate separate from Production.

1. freeze final FE/BE/SQL candidate heads;
2. run exact-head CI and staging E2E again after freeze;
3. capture production backup + Audit Before;
4. prepare backend image/config and SQL change without exposing incompatible frontend traffic;
5. execute the coordinated backend/SQL transition under the approved change window;
6. promote the already validated secure frontend candidate as the traffic-switch event;
7. immediately run production smoke below.

### Path B — merge to `main` automatically deploys Production

Do **not** merge frontend PR #2 separately. Build a reconciled secure final frontend candidate first.

The merge to `main` itself is a production change and requires the same explicit rollout authorization as backend/SQL. The cutover plan must ensure the backend/profile contract is compatible at the moment the new main deployment receives traffic.

No automatic merge is allowed.

## Production smoke — Stage 0: infrastructure identity

Before functional traffic checks:

- Vercel active Production deployment ID equals the authorized candidate;
- backend Lambda image digest equals the authorized candidate ECR digest;
- backend runtime storage mode is `production`;
- production Mastering bucket is exactly `amzn-rqs-bunker-sa`;
- production backend does not point at staging Supabase;
- production frontend does not point at staging Supabase/backend;
- no unapproved environment/config drift is present.

Failure => **COORDINATED ROLLBACK**.

## Production smoke — Stage 1: read-only HTTP

Required:

```text
GET /health -> 200
GET /mastering/v2/capabilities -> 200
legacy /mastering/process -> 410 only after secure frontend is confirmed live
```

Also verify expected security headers and production CORS behavior.

Failure => stop further smoke mutations and enter rollback decision.

## Production smoke — Stage 2: authentication boundary

Using a dedicated production smoke account only:

- public landing remains accessible as designed;
- Mastering Preview and Full Master require login;
- real production JWT identifies the expected smoke user;
- own profile read succeeds;
- browser sensitive profile UPDATE remains denied;
- browser direct quota RPC remains denied;
- no auth token is sent to signed S3 PUT/GET hosts.

Do not use a normal customer account.

## Production smoke — Stage 3: controlled Mastering transaction

Only after Stages 0-2 PASS and the rollout authorization explicitly includes one production smoke transaction:

1. use an approved non-customer audio fixture;
2. obtain authenticated presign under `uploads/{smoke-user-id}/...`;
3. PUT only to the approved production Mastering bucket;
4. request Preview and require a valid result;
5. prove Preview did not increment Full Master quota;
6. request exactly one Full Master;
7. require `masters/{smoke-user-id}/...` output and successful download;
8. prove quota incremented exactly once;
9. inspect logs for unexpected auth/quota/storage/DSP errors;
10. clean test objects using the approved operator path, or record lifecycle cleanup evidence.

Do not repeat Full Master merely to gain confidence. Existing concurrency/idempotency gates provide that assurance.

## Production smoke — Stage 4: frontend UX

Confirm on the actual Production frontend:

- authenticated Preview A/B works;
- Preview selection/window behavior is intact;
- successful Full Master refreshes server-authoritative profile state;
- no browser request targets staging systems;
- Free limit/waitlist UX is intact;
- no payment action becomes available unless `LIVE_PAYMENT` was explicitly approved.

## Audit After

After smoke PASS:

- run production Audit After;
- compare security/RLS/RPC/profile authority with Audit Before;
- confirm no active orphan quota reservations from smoke;
- confirm no unexpected production S3 keys outside the smoke-user namespaces;
- confirm application logs contain no new critical markers;
- record deployment IDs/digests and smoke evidence hashes.

Only then may the release be classified `CONTROLLED_PRODUCTION_VALIDATION: PASS`.

# Rollback

Rollback is **coordinated**, not component-by-component unless compatibility has been explicitly proven.

## Immediate rollback triggers

- `/health` or `/mastering/v2/capabilities` fails;
- auth/JWT/profile authority fails;
- unexpected client profile write becomes possible;
- quota increments incorrectly or cannot release after failure;
- output/input uses the wrong S3 namespace/bucket;
- production frontend points to staging or vice versa;
- staging/production secret boundary is violated;
- DSP smoke materially differs from the already validated Mastering V2 behavior;
- widespread 4xx/5xx or critical log regression;
- any release component identity differs from the authorized snapshot.

## Rollback order — before frontend traffic switch

If backend/SQL preparation fails **before** the secure frontend is serving Production:

1. do not promote/merge the new frontend;
2. restore backend to the captured previous ECR digest/config if it was changed;
3. execute reviewed SQL rollback only if its fail-closed preconditions pass;
4. verify previous `/health` behavior;
5. run read-only Audit After-Rollback;
6. keep release HOLD.

## Rollback order — after traffic switch

If the new frontend has received Production traffic, treat rollback as one logical transaction:

1. stop further rollout actions and preserve logs/evidence;
2. select the captured previous compatible frontend deployment but do not assume frontend-only rollback is safe;
3. restore backend to the captured previous ECR digest/config as part of the same rollback plan;
4. run the reviewed DB rollback only when its safety checks permit it;
5. restore previous frontend traffic state;
6. verify old frontend/backend/profile authority compatibility;
7. run `/health` and previous-production smoke checks;
8. run Audit After-Rollback;
9. classify release `ROLLED_BACK / HOLD`.

If SQL rollback refuses because reservation/data preconditions are not safe, **do not force it**. Keep the system in the safest compatible forward state, stop traffic-affecting changes and escalate the recovery plan using captured evidence.

## Credential rule during rollback

Previously exposed credentials must never be restored merely to recreate an old deployment.

If credentials have already been rotated, an old application image may be rolled back only with replacement credentials that are compatible with that image. Reintroducing an exposed Stripe/Supabase secret is forbidden.

## Payment rule during rollback

If Project 1 ships as `WAITLIST_ONLY`, payment must remain unavailable throughout rollout and rollback.

If `LIVE_PAYMENT` is later approved, Stripe/webhook entitlement validation and credential rotation become separate mandatory release gates before enabling it.

## Final classification

Production remains HOLD until all staging, cutover, backup, audit and authorization gates are complete.

```text
MERGE: HOLD
PRODUCTION DEPLOY: HOLD
PRODUCTION SQL: HOLD
AUTO-MERGE: FORBIDDEN
```
