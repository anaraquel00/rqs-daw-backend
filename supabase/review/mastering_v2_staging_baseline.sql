-- =========================================================
-- RQS MASTERING V2 — ISOLATED STAGING BASELINE ALIGNMENT
-- MUTATING / STAGING ONLY / NEVER PRODUCTION
--
-- Purpose: the existing rqs-daw-staging project was created for Uplink and its
-- public.profiles table intentionally has a reduced synthetic schema. This
-- script adds only the profile fields/security surface required to validate
-- Mastering V2 without copying production user data and without breaking the
-- existing synthetic Uplink profile.
-- =========================================================

begin;

do $preflight$
declare
  v_rls boolean;
  v_policy_count integer;
begin
  if to_regclass('public.profiles') is null then
    raise exception 'STAGING_PROFILES_TABLE_NOT_FOUND';
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='id'
  ) or not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='role'
  ) or not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='monthly_clicks'
  ) or not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='click_quota'
  ) then
    raise exception 'STAGING_UPLINK_PROFILE_BASELINE_MISMATCH';
  end if;

  if exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles'
      and column_name in ('email', 'completed_masters')
  ) then
    raise exception 'STAGING_MASTERING_PROFILE_FIELDS_ALREADY_PRESENT';
  end if;

  select c.relrowsecurity into v_rls
  from pg_class c
  join pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relname='profiles';

  if coalesce(v_rls, false) then
    raise exception 'STAGING_PROFILES_RLS_ALREADY_ENABLED';
  end if;

  select count(*) into v_policy_count
  from pg_policies
  where schemaname='public' and tablename='profiles';

  if v_policy_count <> 0 then
    raise exception 'STAGING_PROFILES_POLICIES_UNEXPECTED';
  end if;

  if not has_table_privilege('service_role', 'public.profiles', 'SELECT')
     or not has_table_privilege('service_role', 'public.profiles', 'UPDATE') then
    raise exception 'STAGING_SERVICE_ROLE_PROFILE_ACCESS_MISSING';
  end if;

  if exists (
    select 1 from public.profiles
    where role is null or role::text not in ('free','premium')
  ) then
    raise exception 'STAGING_PROFILE_ROLE_INVALID';
  end if;
end;
$preflight$;

alter table public.profiles
  add column email text null,
  add column completed_masters integer not null default 0;

alter table public.profiles enable row level security;

-- Browser roles start Mastering staging with no profile write authority.
revoke all on table public.profiles from anon, authenticated, public;
grant select on table public.profiles to authenticated;

create policy "Usuários autenticados leem o próprio perfil"
on public.profiles
for select
to authenticated
using ((select auth.uid()) = id);

commit;

-- Post-alignment proof. This section is READ ONLY.
select
  exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='completed_masters'
  ) as completed_masters_present,
  exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='email'
  ) as email_present,
  (
    select c.relrowsecurity from pg_class c
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relname='profiles'
  ) as profiles_rls_enabled,
  has_table_privilege('authenticated','public.profiles','SELECT') as authenticated_select_present,
  not has_table_privilege('authenticated','public.profiles','UPDATE') as authenticated_update_denied,
  not has_table_privilege('anon','public.profiles','UPDATE') as anon_update_denied,
  has_table_privilege('service_role','public.profiles','SELECT')
    and has_table_privilege('service_role','public.profiles','UPDATE')
    as service_role_access_present;
