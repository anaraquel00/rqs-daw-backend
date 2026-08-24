-- =========================================================
-- RQS MASTERING V2 — ISOLATED STAGING BASELINE ROLLBACK
-- MUTATING / STAGING ONLY / NEVER PRODUCTION
--
-- Run only after mastering_v2_security_rollback.sql has removed the Mastering
-- quota table/RPCs. Restores the observed synthetic Uplink staging profiles
-- schema/security baseline without deleting the existing Uplink profile row.
-- =========================================================

begin;

do $preflight$
begin
  if to_regclass('public.mastering_quota_reservations') is not null
     or to_regprocedure('public.reserve_mastering_quota(uuid,uuid)') is not null
     or to_regprocedure('public.confirm_mastering_quota(uuid,uuid)') is not null
     or to_regprocedure('public.release_mastering_quota(uuid,uuid)') is not null then
    raise exception 'MASTERING_SECURITY_ROLLBACK_REQUIRED_FIRST';
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='email'
  ) or not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='completed_masters'
  ) then
    raise exception 'STAGING_MASTERING_ALIGNMENT_FIELDS_MISSING';
  end if;

  if exists (
    select 1 from public.profiles
    where completed_masters <> 0
  ) then
    raise exception 'STAGING_COMPLETED_MASTERS_NONZERO_REQUIRES_REVIEW';
  end if;

  if exists (
    select 1 from public.profiles
    where email is not null
  ) then
    raise exception 'STAGING_EMAIL_DATA_PRESENT_REQUIRES_REVIEW';
  end if;
end;
$preflight$;

-- Remove Mastering-only policy and fields.
drop policy if exists "Permitir que usuários atualizem seus próprios perfis"
on public.profiles;
drop policy if exists "Usuários autenticados leem o próprio profil"
on public.profiles;
drop policy if exists "Usuários autenticados leem o próprio perfil"
on public.profiles;

alter table public.profiles disable row level security;

revoke all on table public.profiles from anon, authenticated, service_role, public;

grant references, trigger, truncate
on table public.profiles
to anon, authenticated;

grant select, update, references, trigger, truncate
on table public.profiles
to service_role;

alter table public.profiles
  drop column completed_masters,
  drop column email;

commit;

select
  not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles'
      and column_name in ('email','completed_masters')
  ) as mastering_columns_removed,
  not (
    select c.relrowsecurity from pg_class c
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relname='profiles'
  ) as profiles_rls_disabled,
  (select count(*) from pg_policies where schemaname='public' and tablename='profiles') = 0
    as profile_policies_removed;
