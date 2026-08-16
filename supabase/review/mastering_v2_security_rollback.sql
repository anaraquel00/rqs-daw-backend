-- =========================================================
-- RQS MASTERING V2 SECURITY — REVIEWED ROLLBACK CANDIDATE
-- DO NOT RUN BLINDLY.
--
-- This is a compatibility rollback, not a restoration of the insecure broad
-- production ACL. If the secure application rollout must be reverted, the old
-- frontend needs only owner-scoped completed_masters UPDATE. Broad role/profile
-- write authority is intentionally NOT restored.
-- =========================================================

begin;

do $preflight$
begin
  if to_regclass('public.mastering_quota_reservations') is null then
    raise exception 'MASTERING_QUOTA_RESERVATIONS_NOT_FOUND';
  end if;

  if exists (
    select 1 from public.mastering_quota_reservations where status = 'completed'
  ) then
    raise exception 'COMPLETED_RESERVATIONS_PRESENT_REQUIRES_MANUAL_RECONCILIATION';
  end if;

  if exists (
    select 1 from public.mastering_quota_reservations where status = 'reserved'
  ) then
    raise exception 'ACTIVE_RESERVATIONS_PRESENT';
  end if;

  if has_table_privilege('authenticated', 'public.profiles', 'INSERT')
     or has_table_privilege('authenticated', 'public.profiles', 'UPDATE')
     or has_table_privilege('authenticated', 'public.profiles', 'DELETE')
     or has_table_privilege('authenticated', 'public.profiles', 'TRUNCATE') then
    raise exception 'AUTHENTICATED_PROFILE_WRITE_AUTHORITY_ALREADY_PRESENT';
  end if;

  if has_table_privilege('anon', 'public.profiles', 'INSERT')
     or has_table_privilege('anon', 'public.profiles', 'UPDATE')
     or has_table_privilege('anon', 'public.profiles', 'DELETE')
     or has_table_privilege('anon', 'public.profiles', 'TRUNCATE') then
    raise exception 'ANON_PROFILE_WRITE_AUTHORITY_UNEXPECTED';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'profiles' and cmd = 'UPDATE'
  ) then
    raise exception 'PROFILE_UPDATE_POLICY_ALREADY_PRESENT';
  end if;
end;
$preflight$;

revoke all on function public.reserve_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;
revoke all on function public.confirm_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;
revoke all on function public.release_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

drop function public.reserve_mastering_quota(uuid, uuid);
drop function public.confirm_mastering_quota(uuid, uuid);
drop function public.release_mastering_quota(uuid, uuid);
drop table public.mastering_quota_reservations;

-- Old Final Beta frontend compatibility: authenticated users may update only
-- their own completed_masters column. role/email/Uplink quota fields stay
-- non-writable from the browser.
create policy "Permitir que usuários atualizem seus próprios perfis"
on public.profiles
for update
to authenticated
using (auth.uid() = id)
with check (auth.uid() = id);

grant select on table public.profiles to authenticated;
grant update (completed_masters) on table public.profiles to authenticated;

-- Defensive: anonymous browser writes remain denied.
revoke insert, update, delete, truncate
on table public.profiles
from anon, public;

commit;
