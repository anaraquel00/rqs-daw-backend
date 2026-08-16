# Mastering V2 Project 1 — Staging Validation Gate

Status: OPEN  
Target: isolated Supabase staging + non-production backend/frontend staging

## Required PASS evidence

### Database

- migration preflight PASS
- reservation table RLS enabled
- no anon/authenticated access to reservation table
- reserve/confirm/release RPCs are SECURITY INVOKER
- fixed empty search_path
- service_role execute only
- profile role/completed_masters constraints compatible with current schema
- read-only security audit PASS

### Quota concurrency

Use independent database sessions, not sequential calls in one session.

Free profile fixture:
- `completed_masters = 2`
- start multiple reserve calls concurrently
- exactly one request may reserve the final Free slot
- all remaining concurrent requests must fail with quota exceeded
- a released failed job must make the slot available again
- a successful confirmation must increment completed_masters exactly once
- duplicate confirmation must not increment again

Premium profile fixture:
- concurrent reservations allowed by mastering quota policy
- completed_masters must not be changed by the V2 quota functions

### HTTP / auth

- capabilities 200 without login
- V2 presigned upload without Bearer token -> 401
- V2 process without Bearer token -> 401
- invalid/expired user token -> 401
- another user's S3 key -> 403
- authenticated upload key contains only authenticated user id namespace
- Preview succeeds and does not consume Full Master quota
- Full Master at Free 2/3 reserves and confirms one slot
- Free 3/3 -> 429
- failed Full Master releases its reservation
- legacy `/mastering/process` -> 410
- no raw token/server key in application logs

### Frontend follow-up

- authenticated session token sent only to RQS backend V2 endpoints
- use `/mastering/v2/presigned-url`
- frontend no longer increments completed_masters as authoritative quota state
- profile is refreshed after confirmed Full Master
- Preview and A/B behavior unchanged

### Real audio

- selected 15-second Preview window exactness
- final Full Master output compared against validated V2 behavior
- no unexplained DSP regression
- output downloadable and playable

No production rollout is allowed until all applicable staging gates above are PASS and explicitly reviewed.
