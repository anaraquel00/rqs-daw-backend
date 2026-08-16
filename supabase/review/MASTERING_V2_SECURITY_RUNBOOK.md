# Mastering V2 Project 1 Security Runbook

Status: REVIEW CANDIDATE  
Scope: backend Mastering V2 secure integration only  
Production mutation: NONE by committing this file

## Preconditions

1. Current backend `main` contains Uplink Tracking Security V3.2.
2. Mastering V2 DSP source matches validated release `mastering-v2-v1`.
3. Production logical backup and rollback path are confirmed before any SQL or deploy.
4. Required server environment values exist without printing them:
   - `SUPABASE_URL`
   - `SUPABASE_SECRET_KEY`
   - AWS credentials/role required by the existing S3 integration.
5. Frontend sends the authenticated Supabase access token as `Authorization: Bearer <token>`.
6. Frontend uses `/mastering/v2/presigned-url`; legacy unauthenticated S3 keys are not accepted by V2 production processing.
7. The legacy `/mastering/process` endpoint remains retired so it cannot bypass V2 authorization/quota.

## Deployment order

1. Run the reviewed security migration in isolated staging.
2. Run `mastering_v2_security_audit.sql` in staging.
3. Validate quota concurrency:
   - Free profile with `completed_masters = 2`
   - multiple simultaneous reservation calls
   - exactly one reservation may consume the final slot
   - failed work must release its reservation
   - successful work must confirm exactly once.
4. Deploy backend candidate to staging.
5. Validate:
   - capabilities remains public/read-only
   - missing/invalid JWT -> 401
   - another user's S3 key -> 403
   - secure presigned key is namespaced by authenticated user id
   - Preview does not consume quota
   - successful Full Master confirms quota
   - failed Full Master releases quota
   - Free 3/3 -> 429
   - Premium -> allowed
   - output key is namespaced by user id
   - legacy `/mastering/process` -> 410
   - no raw token or service key appears in logs.
6. Connect the frontend security follow-up to staging.
7. Run HTTP/security E2E and real-audio regression.
8. Only after staging PASS: take/verify production backup and run an Audit Before snapshot.
9. Apply the reviewed migration once in production.
10. Deploy backend and frontend in the approved order.
11. Run controlled production validation.
12. Run Audit After and update `PROJECT_STATE.md`.

## Supabase API-key compatibility

The backend supports both:
- current `sb_secret_*` server keys, sent in the `apikey` header only for admin REST/RPC calls;
- legacy JWT-based `service_role` keys, which also use `Authorization: Bearer`.

User requests always carry the user's Supabase Auth JWT in `Authorization: Bearer <user-jwt>`.
Secrets must never be printed or returned to the client.

## Rollback

If migration succeeded but application validation fails:

- stop further rollout;
- revert application deployment to the previous backend/frontend release;
- do not drop quota tables/functions blindly if reservations exist;
- inspect `mastering_quota_reservations`;
- prepare an explicit reviewed rollback SQL from actual production state.

Never use `CASCADE` for rollback without an audited dependency review.
