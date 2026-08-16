# Mastering V2 — quota rejection cleanup regression note

Status: CLOSED / PASS
Date: 2026-08-16

## Evidence

The first real staging HTTP quota validation passed its functional assertions, but the retained `server.stderr.log` contained:

```text
[MASTERING V2] quota release failed.
```

The database was confirmed clean after that run (`completed_masters` restored, zero total/active test reservations).

## Root cause

The controller generated and stored `quotaReservationId` before calling `reserve_mastering_quota()`. On the expected Free 3/3 rejection, `reserve_mastering_quota()` returned `MASTERING_QUOTA_EXCEEDED` before creating a reservation. The generic catch block then attempted `release_mastering_quota()` merely because an ID had been generated, causing a misleading `MASTERING_RESERVATION_NOT_FOUND` cleanup failure log.

This did not consume quota and did not leave a reservation, but it made the failure path noisy and could conceal a real release failure in operational logs.

## Fix

The controller tracks `quotaReserved` separately and sets it only after `reserve_mastering_quota()` succeeds. Release is attempted only when a reservation was actually acquired and not confirmed.

The staging HTTP quota validator also fails if the server emits the old `quota release failed` marker.

## Revalidation — PASS

Real staging rerun completed successfully:

```text
STAGING_QUOTA_HTTP_REAL_JWT_ACQUIRED: PASS
STAGING_QUOTA_HTTP_PREFLIGHT: PASS
STAGING_QUOTA_HTTP_CANDIDATE_INSTALL: PASS
STAGING_QUOTA_HTTP_CANDIDATE_HEALTH: PASS
STAGING_HTTP_QUOTA_RESERVE_RELEASE: PASS
STAGING_HTTP_FREE_3_OF_3_429: PASS
STAGING_HTTP_QUOTA_LOG_CLEAN: PASS
MASTERING_V2_STAGING_HTTP_QUOTA: PASS
S3_REQUESTS_PERFORMED: NONE
PRODUCTION_REQUESTS_PERFORMED: NONE
SECRETS_PRINTED: NONE
STAGING_QUOTA_HTTP_CLEANUP: PASS
```

Retained validation logs show an empty `server.stderr.log`. The staging test identity was restored to its original `completed_masters` state and no quota reservations remain.

Exact-head CI for backend HEAD `3eca46e568e6066ddc3b1dc00457bb2ddda54b23` is green for all Mastering/Uplink validation workflows, including `Mastering V2 Secure Integration`, `Mastering V2 Staging HTTP Quota Validator`, `Mastering V2 Storage Isolation`, auth/profile hardening, staging auth, staging HTTP auth/ownership, and Uplink regression.

## Gate

`MASTERING_V2_STAGING_HTTP_QUOTA: CLOSED / PASS`

The quota-release regression no longer blocks the next staging gate. Dedicated non-production S3 storage remains required before real staging upload / Preview / Full Master E2E.
