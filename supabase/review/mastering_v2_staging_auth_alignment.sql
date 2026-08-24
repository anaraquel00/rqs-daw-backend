-- =========================================================
-- RQS MASTERING V2 — ISOLATED STAGING AUTH ALIGNMENT
-- STAGING ONLY / NEVER PRODUCTION
--
-- Observed staging baseline has auth.users but no signup -> profiles trigger.
-- Add the production-equivalent behavior in hardened form so real staging Auth
-- can be validated without copying production identities.
-- =========================================================

begin;

do $preflight$
declare
  v_trigger_count integer;
begin
  if to_regclass('auth.users') is null then
    raise exception 'STAGING_AUTH_USERS_TABLE_NOT_FOUND';
  end if;

  if to_regclass('public.profiles') is null then
    raise exception 'STAGING_PROFILES_TABLE_NOT_FOUND';
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='email'
  ) or not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='profiles' and column_name='completed_masters'
  ) then
    raise exception 'STAGING_MASTERING_PROFILE_FIELDS_MISSING';
  end if;

  if (select count(*) from auth.users) <> 0 then
    raise exception 'STAGING_AUTH_USERS_NOT_EMPTY_BEFORE_ALIGNMENT';
  end if;

  if to_regprocedure('public.handle_new_user()') is not null then
    raise exception 'STAGING_HANDLE_NEW_USER_ALREADY_EXISTS';
  end if;

  select count(*) into v_trigger_count
  from pg_trigger t
  join pg_class c on c.oid = t.tgrelid
  join pg_namespace n on n.oid = c.relnamespace
  where not t.tgisinternal
    and n.nspname='auth'
    and c.relname='users';

  if v_trigger_count <> 0 then
    raise exception 'STAGING_AUTH_USER_TRIGGER_BASELINE_MISMATCH';
  end if;
end;
$preflight$;

create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  insert into public.profiles (id, email, role, completed_masters)
  values (new.id, new.email, 'free', 0);
  return new;
end;
$function$;

revoke all on function public.handle_new_user()
from public, anon, authenticated, service_role;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

commit;
