#!/usr/bin/env python3
"""Native multi-session Mastering V2 quota concurrency validator.

STAGING ONLY. Reads the database connection string from RQS_STAGING_DATABASE_URL.
Never prints the connection string or credentials.

Expected isolated Supabase staging project ref:
    uwrqbywapomuloresoek

Usage (PowerShell):
    $env:RQS_STAGING_DATABASE_URL = '<staging database URL>'
    python scripts/Test-MasteringV2StagingConcurrency.py
    Remove-Item Env:RQS_STAGING_DATABASE_URL
"""

from __future__ import annotations

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - operator prerequisite
    raise SystemExit(
        "Missing psycopg. Install into the active validation venv with: "
        "python -m pip install 'psycopg[binary]>=3.2,<4'"
    ) from exc


EXPECTED_PROJECT_REF = "uwrqbywapomuloresoek"
WORKERS = 8


def require_staging_dsn() -> str:
    dsn = os.environ.get("RQS_STAGING_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("RQS_STAGING_DATABASE_URL is not set.")

    # Supabase direct and pooler connection strings normally contain the
    # project ref either in the hostname or postgres.<project-ref> username.
    # Fail closed instead of trusting an arbitrary database URL.
    if EXPECTED_PROJECT_REF not in dsn:
        raise SystemExit(
            "SAFETY STOP: database URL does not contain the expected isolated "
            f"staging project ref {EXPECTED_PROJECT_REF}."
        )
    return dsn


def service_call(dsn: str, function_name: str, user_id: uuid.UUID, reservation_id: uuid.UUID):
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("set role service_role")
            cur.execute(
                f"select public.{function_name}(%s::uuid, %s::uuid)",
                (str(user_id), str(reservation_id)),
            )
            row = cur.fetchone()
            return row[0] if row else None


def reserve_worker(dsn: str, user_id: uuid.UUID, reservation_id: uuid.UUID):
    try:
        result = service_call(dsn, "reserve_mastering_quota", user_id, reservation_id)
        return {"reservation_id": reservation_id, "status": "accepted", "result": result}
    except Exception as exc:  # psycopg maps PL/pgSQL P0001 to RaiseException
        message = str(exc)
        if "MASTERING_QUOTA_EXCEEDED" in message:
            return {"reservation_id": reservation_id, "status": "quota_exceeded"}
        return {"reservation_id": reservation_id, "status": "unexpected_error", "error": message}


def cleanup(conn, user_ids: list[uuid.UUID]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "delete from public.mastering_quota_reservations where user_id = any(%s::uuid[])",
            ([str(v) for v in user_ids],),
        )
        cur.execute(
            "delete from public.profiles where id = any(%s::uuid[])",
            ([str(v) for v in user_ids],),
        )
    conn.commit()


def main() -> int:
    dsn = require_staging_dsn()
    free_user = uuid.uuid4()
    premium_user = uuid.uuid4()
    fixture_users = [free_user, premium_user]

    admin = psycopg.connect(dsn)
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                select
                  to_regclass('public.mastering_quota_reservations') is not null,
                  to_regprocedure('public.reserve_mastering_quota(uuid,uuid)') is not null,
                  to_regprocedure('public.confirm_mastering_quota(uuid,uuid)') is not null,
                  to_regprocedure('public.release_mastering_quota(uuid,uuid)') is not null,
                  not has_table_privilege('authenticated','public.profiles','UPDATE')
                """
            )
            preflight = cur.fetchone()
            if preflight != (True, True, True, True, True):
                raise RuntimeError(f"STAGING SECURITY PREFLIGHT FAILED: {preflight!r}")

            cur.execute(
                "insert into public.profiles(id, role, completed_masters) values "
                "(%s, 'free', 2), (%s, 'premium', 999)",
                (free_user, premium_user),
            )
        admin.commit()

        # -------------------------------------------------------------
        # FREE 2/3: exactly one of eight independent sessions may reserve
        # the final slot.
        # -------------------------------------------------------------
        free_reservations = [uuid.uuid4() for _ in range(WORKERS)]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [
                pool.submit(reserve_worker, dsn, free_user, reservation_id)
                for reservation_id in free_reservations
            ]
            free_results = [future.result() for future in as_completed(futures)]

        accepted = [r for r in free_results if r["status"] == "accepted"]
        rejected = [r for r in free_results if r["status"] == "quota_exceeded"]
        unexpected = [r for r in free_results if r["status"] == "unexpected_error"]

        if unexpected:
            raise RuntimeError(f"FREE concurrency unexpected errors: {unexpected!r}")
        if len(accepted) != 1 or len(rejected) != WORKERS - 1:
            raise RuntimeError(
                f"FREE concurrency contract failed: accepted={len(accepted)}, "
                f"quota_exceeded={len(rejected)}"
            )

        winning_id = accepted[0]["reservation_id"]
        with admin.cursor() as cur:
            cur.execute(
                "select count(*) from public.mastering_quota_reservations "
                "where user_id=%s and status='reserved' and counts_quota",
                (free_user,),
            )
            if cur.fetchone()[0] != 1:
                raise RuntimeError("FREE reserved row count is not exactly one.")

        # Failed/cancelled work releases the final slot.
        released = service_call(dsn, "release_mastering_quota", free_user, winning_id)
        if released is not True:
            raise RuntimeError(f"FREE release returned {released!r}, expected true.")

        replacement = uuid.uuid4()
        service_call(dsn, "reserve_mastering_quota", free_user, replacement)
        confirmed = service_call(dsn, "confirm_mastering_quota", free_user, replacement)
        duplicate = service_call(dsn, "confirm_mastering_quota", free_user, replacement)
        if confirmed is not True or duplicate is not False:
            raise RuntimeError(
                f"Confirm idempotency failed: first={confirmed!r}, duplicate={duplicate!r}"
            )

        with admin.cursor() as cur:
            cur.execute("select completed_masters from public.profiles where id=%s", (free_user,))
            if cur.fetchone()[0] != 3:
                raise RuntimeError("FREE completed_masters is not exactly 3 after confirmation.")

        # -------------------------------------------------------------
        # PREMIUM: eight independent sessions may reserve concurrently;
        # none consumes completed_masters.
        # -------------------------------------------------------------
        premium_reservations = [uuid.uuid4() for _ in range(WORKERS)]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [
                pool.submit(reserve_worker, dsn, premium_user, reservation_id)
                for reservation_id in premium_reservations
            ]
            premium_results = [future.result() for future in as_completed(futures)]

        premium_accepted = [r for r in premium_results if r["status"] == "accepted"]
        premium_errors = [r for r in premium_results if r["status"] != "accepted"]
        if len(premium_accepted) != WORKERS or premium_errors:
            raise RuntimeError(
                f"PREMIUM concurrency contract failed: accepted={len(premium_accepted)}, "
                f"errors={premium_errors!r}"
            )

        # Release premium test reservations; premium counter must remain unchanged.
        for reservation_id in premium_reservations:
            result = service_call(dsn, "release_mastering_quota", premium_user, reservation_id)
            if result is not True:
                raise RuntimeError(f"Premium release failed for {reservation_id}: {result!r}")

        with admin.cursor() as cur:
            cur.execute("select completed_masters from public.profiles where id=%s", (premium_user,))
            if cur.fetchone()[0] != 999:
                raise RuntimeError("PREMIUM completed_masters changed unexpectedly.")

        print("MASTERING_V2_STAGING_NATIVE_CONCURRENCY: PASS")
        print(f"FREE_SESSIONS: {WORKERS}")
        print("FREE_ACCEPTED: 1")
        print(f"FREE_QUOTA_EXCEEDED: {WORKERS - 1}")
        print("FREE_RELEASE_REOPENED_SLOT: PASS")
        print("FREE_CONFIRM_EXACTLY_ONCE: PASS")
        print("PREMIUM_CONCURRENT_ACCEPTED: 8")
        print("PREMIUM_COUNTER_UNCHANGED: PASS")
        return 0
    finally:
        try:
            admin.rollback()
            cleanup(admin, fixture_users)
            print("STAGING_FIXTURE_CLEANUP: PASS")
        except Exception as cleanup_error:
            print(f"STAGING_FIXTURE_CLEANUP: FAIL ({cleanup_error})", file=sys.stderr)
        finally:
            admin.close()


if __name__ == "__main__":
    raise SystemExit(main())
