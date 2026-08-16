-- =========================================================
-- RQS MASTERING V2 SECURITY AUDIT — READ ONLY
-- Run after the reviewed security migration.
-- =========================================================

select
  to_regclass('public.mastering_quota_reservations') is not null
    as reservation_table_present;

select
  c.relrowsecurity as profiles_rls_enabled
from pg_class as c
join pg_namespace as n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'profiles';

select
  c.relrowsecurity as reservation_rls_enabled
from pg_class as c
join pg_namespace as n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'mastering_quota_reservations';

select
  count(*) = 0 as reservation_policies_absent
from pg_policies
where schemaname = 'public' and tablename = 'mastering_quota_reservations';

-- Browser roles must be read-only against profiles after migration.
select
  has_table_privilege('service_role', 'public.profiles', 'SELECT')
    and has_table_privilege('service_role', 'public.profiles', 'UPDATE')
    as service_role_profiles_access_present,
  has_table_privilege('authenticated', 'public.profiles', 'SELECT')
    as authenticated_profile_read_present,
  not has_table_privilege('authenticated', 'public.profiles', 'INSERT')
    and not has_table_privilege('authenticated', 'public.profiles', 'UPDATE')
    and not has_table_privilege('authenticated', 'public.profiles', 'DELETE')
    and not has_table_privilege('authenticated', 'public.profiles', 'TRUNCATE')
    as authenticated_profile_writes_denied,
  not has_table_privilege('anon', 'public.profiles', 'INSERT')
    and not has_table_privilege('anon', 'public.profiles', 'UPDATE')
    and not has_table_privilege('anon', 'public.profiles', 'DELETE')
    and not has_table_privilege('anon', 'public.profiles', 'TRUNCATE')
    as anon_profile_writes_denied,
  not has_column_privilege('authenticated', 'public.profiles', 'role', 'UPDATE')
    and not has_column_privilege('authenticated', 'public.profiles', 'completed_masters', 'UPDATE')
    as authenticated_security_columns_write_denied;

select
  count(*) = 0 as profile_update_policies_absent
from pg_policies
where schemaname = 'public'
  and tablename = 'profiles'
  and cmd = 'UPDATE';

select
  count(*) = 1 as owner_select_policy_present
from pg_policies
where schemaname = 'public'
  and tablename = 'profiles'
  and cmd = 'SELECT'
  and policyname = 'Usuários autenticados leem o próprio perfil'
  and roles = array['authenticated']::name[];

select
  not has_table_privilege('anon', 'public.mastering_quota_reservations', 'SELECT')
    and not has_table_privilege('anon', 'public.mastering_quota_reservations', 'INSERT')
    and not has_table_privilege('anon', 'public.mastering_quota_reservations', 'UPDATE')
    and not has_table_privilege('anon', 'public.mastering_quota_reservations', 'DELETE')
    as anon_table_dml_denied,
  not has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'SELECT')
    and not has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'INSERT')
    and not has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'UPDATE')
    and not has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'DELETE')
    as authenticated_table_dml_denied,
  has_table_privilege('service_role', 'public.mastering_quota_reservations', 'SELECT')
    and has_table_privilege('service_role', 'public.mastering_quota_reservations', 'INSERT')
    and has_table_privilege('service_role', 'public.mastering_quota_reservations', 'UPDATE')
    and has_table_privilege('service_role', 'public.mastering_quota_reservations', 'DELETE')
    as service_role_table_dml_present;

select
  to_regprocedure('public.reserve_mastering_quota(uuid,uuid)') is not null as reserve_rpc_present,
  to_regprocedure('public.confirm_mastering_quota(uuid,uuid)') is not null as confirm_rpc_present,
  to_regprocedure('public.release_mastering_quota(uuid,uuid)') is not null as release_rpc_present;

select
  count(*) = 3 as exact_mastering_rpc_count,
  coalesce(bool_and(not p.prosecdef), false) as all_security_invoker,
  coalesce(bool_and(p.proconfig = array['search_path=""']::text[]), false) as all_fixed_empty_search_path,
  coalesce(bool_and(not has_function_privilege('anon', p.oid, 'EXECUTE')), false) as anon_execute_denied,
  coalesce(bool_and(not has_function_privilege('authenticated', p.oid, 'EXECUTE')), false) as authenticated_execute_denied,
  coalesce(bool_and(has_function_privilege('service_role', p.oid, 'EXECUTE')), false) as service_role_execute_present
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in ('reserve_mastering_quota', 'confirm_mastering_quota', 'release_mastering_quota');

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
