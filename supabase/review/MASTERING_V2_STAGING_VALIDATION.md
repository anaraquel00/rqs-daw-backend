# Mastering V2 Project 1 — Staging Validation Gate

Status: OPEN  
Target: isolated Supabase staging + non-production backend/frontend staging

## Confirmed baseline evidence — 2026-08-16

Production `public.profiles` was inspected read-only before any Mastering V2 SQL:

- columns include `id`, `email`, `role`, `completed_masters`, `monthly_clicks`, `click_quota`
- RLS enabled
- authenticated own-profile SELECT policy present
- legacy authenticated own-profile UPDATE policy present
- legacy table ACL exposes broad browser table privileges; with the UPDATE policy this makes own-row `role` and `completed_masters` client-mutable
- 3 profiles / 3 auth users / no missing profile linkage
- roles currently: 2 free, 1 premium
- no null/negative `completed_masters`
- `auth.users` has `on_auth_user_created -> public.handle_new_user()`

The isolated `rqs-daw-staging` project is intentionally not production-shaped because it was created for Uplink validation:

- profiles columns: `id`, `role`, `monthly_clicks`, `click_quota`
- `completed_masters` and `email` absent
- RLS disabled / policies absent
- one synthetic premium Uplink profile
- no staging auth users

Therefore the Mastering staging path is explicitly:

1. apply `mastering_v2_staging_baseline.sql` to isolated staging only
2. verify the baseline-alignment proof
3. apply `mastering_v2_security_migration.sql`
4. run the read-only audit
5. run native multi-session quota concurrency
6. run authenticated HTTP/frontend staging validation
7. run real-audio regression

`mastering_v2_staging_baseline.sql` and `mastering_v2_staging_baseline_rollback.sql` are **STAGING ONLY / NEVER PRODUCTION**.

## Required PASS evidence

### Database

- staging baseline alignment preflight PASS
- `completed_masters` present after alignment
- profiles RLS enabled after alignment
- browser profile writes denied
- authenticated owner read preserved
- migration preflight PASS
- reservation table RLS enabled
- no anon/authenticated access to reservation table
- reserve/confirm/release RPCs are SECURITY INVOKER
- fixed empty search_path
- service_role execute only
- role/completed_masters state valid
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

Product policy is confirmed, not open:
- login is required before Preview and Full Master
- Preview never consumes Full Master quota
- Free Final Beta quota is 3 Full Masters total; no 30-day/monthly reset
- after 3/3 Preview remains available, Full Master is blocked and PRO waitlist is shown

Validation:
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
- login requirement is represented in UI before Preview/Full Master
- Preview and A/B behavior unchanged

### Real audio

- selected 15-second Preview window exactness
- final Full Master output compared against validated V2 behavior
- no unexplained DSP regression
- output downloadable and playable

No production rollout is allowed until all applicable staging gates above are PASS and explicitly reviewed.
