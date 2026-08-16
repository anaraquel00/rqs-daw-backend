# Mastering V2 — quota rejection cleanup regression note

Status: FIXED IN CANDIDATE / exact-head revalidation required
Date: 2026-08-16

## Evidence

The real staging HTTP quota validation passed its functional assertions, but the retained `server.stderr.log` contained:

```text
[MASTERING V2] quota release failed.
```

The database was confirmed clean after the run (`completed_masters` restored, zero total/active test reservations).

## Root cause

The controller generated and stored `quotaReservationId` before calling `reserve_mastering_quota()`. On the expected Free 3/3 rejection, `reserve_mastering_quota()` returned `MASTERING_QUOTA_EXCEEDED` before creating a reservation. The generic catch block then attempted `release_mastering_quota()` merely because an ID had been generated, causing a misleading `MASTERING_RESERVATION_NOT_FOUND` cleanup failure log.

This did not consume quota and did not leave a reservation, but it made the failure path noisy and could conceal a real release failure in operational logs.

## Fix

The controller now tracks `quotaReserved` separately and sets it only after `reserve_mastering_quota()` succeeds. Release is attempted only when a reservation was actually acquired and not confirmed.

The staging HTTP quota validator also fails if the server emits the old `quota release failed` marker, so the regression is now explicitly gated.

## Gate

Do not advance to staging S3 / real-audio E2E until:

- exact-head CI is green;
- the real staging HTTP quota validator is rerun against the fixed candidate;
- `STAGING_HTTP_QUOTA_LOG_CLEAN: PASS` is observed;
- `server.stderr.log` contains no quota release failure marker;
- staging profile/quota state is clean after test cleanup.
