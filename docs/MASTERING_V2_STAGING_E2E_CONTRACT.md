# Mastering V2 — Isolated Staging E2E Contract

Status: **CONTRACT ONLY / NO CLOUD MUTATION**

This contract defines the first truthful browser-to-backend-to-S3 validation for Project 1. It must run only after a dedicated staging Lambda, dedicated staging S3 bucket, stable protected Vercel Preview origin, and deterministic Angular staging build are bound.

## Hard boundaries

The E2E gate must fail closed when any of the following is true:

- backend URL equals production `https://m2ud3r3gh7vocnc3hzvhnv4s4m0dmujw.lambda-url.sa-east-1.on.aws`;
- staging bucket equals production `amzn-rqs-bunker-sa`;
- frontend origin equals production `https://studio.raquelsynths.com`;
- frontend staging bundle contains production Supabase ref `ucearnthodrltkvkmhit`;
- staging runtime is not bound to Supabase `uwrqbywapomuloresoek`;
- staging execution role can access the production bucket;
- `RQS_PAYMENT_MODE` is not `disabled` for the Mastering-only staging candidate;
- production Stripe credentials are present in staging;
- Vercel Preview is not proven to build with `npm run build:staging`;
- expected Git HEAD / ECR digest / deployment mapping is missing or drifted.

No wildcard CORS is accepted. Backend CORS must allow the exact protected Preview origin only for this staging candidate.

## Required evidence before any object write

Record without secrets:

```text
FRONTEND_GIT_HEAD=
FRONTEND_VERCEL_DEPLOYMENT_ID=
FRONTEND_STABLE_PREVIEW_ORIGIN=
FRONTEND_BUILD_COMMAND=npm run build:staging

BACKEND_GIT_HEAD=
BACKEND_ECR_DIGEST=
BACKEND_LAMBDA_NAME=rqs-daw-backend-staging
BACKEND_FUNCTION_URL=

STAGING_BUCKET=
STAGING_REGION=sa-east-1
STAGING_EXECUTION_ROLE_ARN=
PRODUCTION_BUCKET_PERMISSION=NONE

SUPABASE_PROJECT_REF=uwrqbywapomuloresoek
RQS_PAYMENT_MODE=disabled
```

Signed URLs, JWTs, passwords, service-role keys and AWS credentials must never be written to evidence.

## Gate A — read-only/runtime preflight

Required PASS markers:

1. candidate `/health` -> HTTP 200;
2. candidate `/mastering/v2/capabilities` -> HTTP 200;
3. exact staging Preview origin receives `Access-Control-Allow-Origin` for itself;
4. production Studio origin receives no CORS authority from staging;
5. `/payment/stripe-webhook` -> HTTP 503 / `PAYMENT_DISABLED` in staging;
6. unauthenticated `/mastering/v2/presigned-url` -> HTTP 401;
7. invalid JWT -> HTTP 401;
8. real staging Supabase sign-in succeeds;
9. signed-in identity resolves to its own staging profile;
10. test profile is `free` and starts at `completed_masters=0` for the full mutation run;
11. authenticated presign returns an `uploads/{user.id}/...` key;
12. presigned URL targets the dedicated staging bucket and never the production bucket;
13. AWS/IAM preflight confirms staging role has no permission to `amzn-rqs-bunker-sa`.

Obtaining a presigned URL is allowed in Gate A because it does not create an S3 object. No PUT is allowed until Gate A is fully PASS.

## Gate B — controlled staging object mutation

Run only with an explicit staging-object-mutation authorization. Use a disposable Free staging identity and a non-production audio fixture.

Sequence:

1. PUT fixture to the authenticated presigned `uploads/{user.id}/...` URL;
2. verify bearer JWT was sent only to the RQS backend and **not** to the signed S3 PUT;
3. request Preview through `/mastering/v2/process` with the user-owned S3 key;
4. require HTTP 200 and non-empty WAV response;
5. re-read profile and prove `completed_masters` is still `0`;
6. request Full Master using the same owned input key;
7. require HTTP 200 JSON with `success=true`, `outputMode=s3` and a signed download URL;
8. require output key namespace `masters/{user.id}/...`;
9. download the rendered master and require a non-empty WAV response;
10. re-read profile and prove `completed_masters` changed exactly `0 -> 1`;
11. prove no request touched the production bucket or production backend;
12. capture server/log evidence with no unexpected error markers.

The validator must not make a second Full Master request merely to test idempotency. Server-side quota/idempotency is already covered by isolated SQL/HTTP concurrency gates.

## Gate C — cleanup / retained evidence

Preferred cleanup uses an operator identity restricted to the dedicated staging bucket. It may delete only the exact test keys created by Gate B.

If cleanup credentials are unavailable, do not broaden IAM. Retain the object-key evidence and rely on the approved staging lifecycle policy; classify cleanup as `DEFERRED_TO_LIFECYCLE`, not silently PASS.

Production bucket cleanup is forbidden.

## Gate D — protected browser Preview E2E

HTTP core E2E is necessary but not sufficient. The protected Vercel Preview must also prove the actual frontend runtime.

Required browser checks:

- Preview deployment is protected and uses the stable approved staging origin;
- loaded bundle contains staging Supabase/backend targets only;
- login uses staging Supabase;
- unauthenticated Preview and Full Master actions are unavailable;
- authenticated Preview A/B completes and remains 15 seconds;
- Preview does not consume quota;
- authenticated Full Master completes and refreshes server-authoritative profile state;
- browser never sends the Supabase bearer token to the signed S3 host;
- no network request targets production Supabase or production backend;
- at Free `3/3`, Full Master is unavailable and the Final Beta / RQS PRO waitlist state is shown;
- waitlist path remains non-payment staging behavior.

## PASS definition

```text
STAGING_RUNTIME_PREFLIGHT: PASS
STAGING_AUTH_OWNERSHIP: PASS
STAGING_PRESIGN_BUCKET_ISOLATION: PASS
STAGING_PREVIEW_E2E: PASS
STAGING_PREVIEW_QUOTA_UNCHANGED: PASS
STAGING_FULL_MASTER_E2E: PASS
STAGING_FULL_MASTER_QUOTA_EXACTLY_ONCE: PASS
STAGING_BROWSER_NETWORK_ISOLATION: PASS
STAGING_PRODUCTION_REQUESTS: NONE
STAGING_PRODUCTION_BUCKET_ACCESS: NONE
STAGING_SECRETS_PRINTED: NONE
MASTERING_V2_ISOLATED_STAGING_E2E: PASS
```

Anything less remains **HOLD** for production cutover.
