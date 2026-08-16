-- =========================================================
-- RQS MASTERING V2 SECURITY — REVIEWED ROLLBACK CANDIDATE
-- DO NOT RUN BLINDLY.
-- Preconditions below must be verified before execution.
-- =========================================================

begin;

-- Fail closed if any reservation has already been completed. Once a completed
-- reservation exists, completed_masters may have been incremented and rollback
-- needs an operator-reviewed reconciliation rather than destructive teardown.
do $preflight$
begin
  if to_regclass('public.mastering_quota_reservations') is null then
    raise exception 'MASTERING_QUOTA_RESERVATIONS_NOT_FOUND';
  end if;

  if exists (
    select 1
    from public.mastering_quota_reservations
    where status = 'completed'
  ) then
    raise exception 'COMPLETED_RESERVATIONS_PRESENT_REQUIRES_MANUAL_RECONCILIATION';
  end if;

  if exists (
    select 1
    from public.mastering_quota_reservations
    where status = 'reserved'
  ) then
    raise exception 'ACTIVE_RESERVATIONS_PRESENT';
  end if;

  -- Rollback restores exactly the expected pre-migration browser quota ACL.
  -- Refuse to continue if client UPDATE authority has already reappeared or
  -- anonymous access is present, because that would mean the live ACL drifted.
  if has_table_privilege('authenticated', 'public.profiles', 'UPDATE')
     or has_column_privilege('authenticated', 'public.profiles', 'completed_masters', 'UPDATE') then
    raise exception 'AUTHENTICATED_QUOTA_UPDATE_ALREADY_PRESENT';
  end if;

  if has_table_privilege('anon', 'public.profiles', 'UPDATE')
     or has_column_privilege('anon', 'public.profiles', 'completed_masters', 'UPDATE') then
    raise exception 'ANON_PROFILE_UPDATE_UNEXPECTED';
  end if;
end;
$preflight$;

revoke all
on function public.reserve_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

revoke all
on function public.confirm_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

revoke all
on function public.release_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

drop function public.reserve_mastering_quota(uuid, uuid);
drop function public.confirm_mastering_quota(uuid, uuid);
drop function public.release_mastering_quota(uuid, uuid);

drop table public.mastering_quota_reservations;

-- Restore the exact temporary Final Beta client behavior that the migration
-- retired: authenticated may update only completed_masters. No table-level
-- UPDATE and no anon UPDATE are restored.
grant update (completed_masters)
on table public.profiles
to authenticated;

commit;
