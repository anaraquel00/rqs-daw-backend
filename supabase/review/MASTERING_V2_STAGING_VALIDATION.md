# Mastering V2 Project 1 — Staging Validation Gate

Status: IN PROGRESS — database/auth/HTTP/quota gates PASS; S3/real-audio OPEN  
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

The isolated `rqs-daw-staging` project was initially not production-shaped because it was created for Uplink validation. A reviewed staging-only baseline alignment was applied before the Mastering V2 security migration. No production user data was copied.

## Closed staging gates

### Database / security — PASS

- staging baseline alignment preflight PASS
- `completed_masters` present after alignment
- profiles RLS enabled
- browser profile writes denied
- authenticated owner read preserved
- Mastering V2 migration PASS
- reservation table RLS enabled
- no anon/authenticated access to reservation table
- reserve/confirm/release RPCs SECURITY INVOKER with fixed empty search_path
- service-role-only execution surface
- role/completed_masters state valid
- read-only Audit After PASS
- SQL functional fixture + cleanup PASS

### Native quota concurrency — PASS

Validated with 8 independent PostgreSQL sessions:

- Free 2/3: exactly 1 accepted + 7 `MASTERING_QUOTA_EXCEEDED`
- release reopens the final slot
- confirm increments exactly once
- duplicate confirm does not increment again
- Premium: 8/8 accepted, counter unchanged
- cleanup PASS

### Real staging Auth/JWT — PASS

- real disposable staging identity created and e-mail confirmed
- signup trigger creates `profiles` row as `free / completed_masters=0`
- real JWT verified by staging Supabase Auth
- authenticated owner profile SELECT PASS
- browser attempt to update protected profile fields denied
- browser direct quota RPC denied

### Real candidate HTTP auth / ownership — PASS

Using the actual candidate Express controller with the real staging JWT:

- no auth -> 401
- invalid JWT -> 401
- legacy `/mastering/process` -> 410
- foreign user's S3 key -> 403
- path-escape S3 key -> 400
- no S3 requests performed in this gate
- no production requests performed

### Real candidate HTTP quota / failure semantics — PASS

Validated against real staging quota RPCs using the retained staging identity and server-only staging key:

- Free 2/3 reserve succeeds
- controlled pre-S3 failure releases reservation
- `completed_masters` remains unchanged after failed Full Master
- Free 3/3 returns 429 `MASTERING_QUOTA_EXCEEDED` before S3
- no active reservation remains
- quota-rejection path no longer emits the stale `quota release failed` cleanup warning
- `STAGING_HTTP_QUOTA_LOG_CLEAN: PASS`
- staging identity restored to original state
- test reservations cleanup PASS
- retained `server.stderr.log` empty

## Product policy — CONFIRMED

- login is required before Preview and Full Master
- Preview never consumes Full Master quota
- Free Final Beta quota is 3 Full Masters total; no 30-day/monthly reset
- after 3/3 Preview remains available, Full Master is blocked and PRO waitlist is shown

## Remaining staging gates

### Dedicated non-production S3 — OPEN / REQUIRED

Before any real staging upload:

- create/provision a dedicated non-production S3 bucket or equivalent isolated storage namespace
- production bucket must not be usable from staging
- staging backend must use explicit `RQS_MASTERING_V2_STORAGE_ENV=staging`
- staging bucket must be explicit in `RQS_MASTERING_V2_BUCKET_NAME`
- validate block-public-access / ownership / upload-download-delete path
- no production storage object may be touched by staging tests

### Frontend authenticated integration — OPEN

- authenticated session token sent only to RQS backend V2 endpoints
- use `/mastering/v2/presigned-url`
- frontend no longer increments `completed_masters` as authoritative quota state
- profile refreshed after confirmed Full Master
- login requirement represented in UI before Preview/Full Master
- Preview and A/B behavior unchanged

### Real audio — OPEN / REQUIRED

- selected 15-second Preview window exactness
- real staging upload/download path
- successful Full Master increments quota exactly once
- failed Full Master releases quota
- output key namespaced by authenticated user id
- final Full Master output compared against validated V2 behavior
- no unexplained DSP regression
- output downloadable and playable

## Release rule

No production rollout is allowed until all applicable staging gates above are PASS and explicitly reviewed.
