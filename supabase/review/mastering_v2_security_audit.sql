-- =========================================================
-- RQS MASTERING V2 SECURITY AUDIT — READ ONLY
-- Run after the reviewed security migration.
-- =========================================================

select
  to_regclass('public.mastering_quota_reservations') is not null
    as reservation_table_present;

select
  c.relrowsecurity as reservation_rls_enabled
from pg_class as c
join pg_namespace as n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname = 'mastering_quota_reservations';

select
  count(*) = 0 as reservation_policies_absent
from pg_policies
where schemaname = 'public'
  and tablename = 'mastering_quota_reservations';

select
  to_regprocedure('public.reserve_mastering_quota(uuid,uuid)') is not null
    as reserve_rpc_present,
  to_regprocedure('public.confirm_mastering_quota(uuid,uuid)') is not null
    as confirm_rpc_present,
  to_regprocedure('public.release_mastering_quota(uuid,uuid)') is not null
    as release_rpc_present;

select
  p.proname,
  p.prosecdef as security_definer,
  p.proconfig,
  has_function_privilege('anon', p.oid, 'EXECUTE') as anon_execute,
  has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_execute,
  has_function_privilege('service_role', p.oid, 'EXECUTE') as service_role_execute
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in (
    'reserve_mastering_quota',
    'confirm_mastering_quota',
    'release_mastering_quota'
  )
order by p.proname;

select
  count(*) = 0 as invalid_profile_mastering_state
from public.profiles
where role is null
   or role::text not in ('free', 'premium')
   or completed_masters is null
   or completed_masters < 0;

select
  count(*) = 0 as invalid_reservation_state
from public.mastering_quota_reservations
where status not in ('reserved', 'completed', 'released')
   or user_id is null
   or counts_quota is null
   or created_at is null;

select
  count(*) filter (where status = 'reserved') as active_reservations,
  count(*) filter (where status = 'completed') as completed_reservations,
  count(*) filter (where status = 'released') as released_reservations
from public.mastering_quota_reservations;
