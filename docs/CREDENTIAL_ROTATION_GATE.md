# Project 1 — Credential Rotation Gate

Status: **EXPOSURE CONFIRMED / ROTATION REQUIRED / NO ROTATION EXECUTED**

This document contains no credential values. It defines the controlled gate for credentials that appeared in historical project material.

## In-scope credential classes

```text
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
SUPABASE_SECRET_KEY
```

Do not copy existing values into tickets, Git, chat evidence, screenshots or validation logs.

## Confirmed code consumers on the secure backend candidate

### `SUPABASE_SECRET_KEY`

- `src/lib/supabase-server.js`
  - server-side Supabase API key;
  - authenticated user verification upstream calls;
  - server-authorized quota RPC calls.
- `src/controllers/payment.js`
  - privileged profile update path when payments are enabled.

### `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`

- `src/controllers/payment.js`
  - Stripe SDK initialization;
  - webhook signature validation.

Phase A staging explicitly supports `RQS_PAYMENT_MODE=disabled`, so isolated Mastering-only staging must not receive production Stripe credentials.

## Safety rule

Rotation is a controlled production security change. It is not coupled automatically to merge or Mastering deployment and requires explicit authorization.

Previously exposed values must never be restored during rollback.

## Rotation sequence

### 1. Inventory

Before generating replacements, record only names and consumers:

```text
credential class
current environment(s)
runtime/service consumers
CI consumers, if any
operator/tool consumers, if any
last-known deployment using it
replacement owner
rollback compatibility requirements
```

Search runtime configuration, deployment templates and CI secret names. Do not print values.

### 2. Prepare replacement

Generate a replacement through the current vendor-supported control plane.

Requirements:

- replacement is not pasted into chat/Git;
- replacement is stored directly in the approved secret/runtime store;
- consumer mapping is complete before revoking the old value;
- the old value remains active only for the shortest controlled overlap needed for validation.

Exact vendor UI/API commands must be revalidated against current Stripe/Supabase documentation at execution time.

### 3. Stage consumers

Update one controlled environment at a time.

For `SUPABASE_SECRET_KEY`, validate at minimum:

- backend boots;
- real user JWT verification succeeds;
- own profile reads succeed;
- server quota reserve/confirm/release succeeds;
- browser direct sensitive writes/RPC remain denied;
- no staging/production project-ref crossover occurs.

For Stripe credentials, do not enable live payments merely to test rotation. If Project 1 is `WAITLIST_ONLY`, payment remains disabled and Stripe rotation is validated against the existing webhook integration only in an explicitly approved isolated/test path.

### 4. Validate replacement

Evidence must contain status only, never secret material:

```text
REPLACEMENT_CONFIGURED: PASS
BACKEND_BOOT: PASS
SUPABASE_AUTH: PASS
SUPABASE_SERVER_RPC: PASS
STRIPE_SIGNATURE_PATH: PASS | NOT_APPLICABLE_WAITLIST_ONLY
OLD_KEY_USAGE_CHECK: PASS
SECRETS_PRINTED: NONE
```

### 5. Old-key usage check

Before revocation, inspect the available vendor/runtime logs and deployment inventory for consumers still using the old credential.

If usage cannot be distinguished reliably, do not guess. Extend the observation/validation path or explicitly enumerate every known consumer and prove each has moved.

### 6. Revoke old value

Only after replacement validation and old-consumer closure.

Immediately after revocation:

- repeat health/auth/quota checks;
- monitor authentication/upstream failures;
- verify payment state matches the approved Project 1 payment mode;
- record revocation timestamp and non-secret credential identifier/version if the provider exposes one.

## Rollback rule

Rollback means restoring application/config compatibility using the **replacement** credential set.

It never means reactivating or re-entering an exposed old value.

If an older application build cannot operate with the replacement credential, that incompatibility is a release blocker and must be solved before rotation/release.

## PASS definition

```text
CREDENTIAL_CONSUMER_INVENTORY: PASS
REPLACEMENTS_CREATED_AND_STORED_SECURELY: PASS
ALL_CONSUMERS_MIGRATED: PASS
REPLACEMENT_RUNTIME_VALIDATION: PASS
OLD_KEY_USAGE: NONE_CONFIRMED
OLD_VALUES_REVOKED: PASS
POST_REVOCATION_SMOKE: PASS
SECRETS_IN_EVIDENCE: NONE
CREDENTIAL_ROTATION_GATE: PASS
```

Until then:

```text
CREDENTIAL_ROTATION_GATE: HOLD
PRODUCTION RELEASE AUTHORIZATION: HOLD
```
