-- =========================================================
-- RQS MASTERING V2 — AUTH PROFILE CREATION HARDENING
-- PRODUCTION REVIEW CANDIDATE — DO NOT RUN WITHOUT BACKUP,
-- AUDIT BEFORE, STAGING VALIDATION AND EXPLICIT APPROVAL.
--
-- Observed production baseline:
--   public.handle_new_user() exists as SECURITY DEFINER
--   auth.users has trigger on_auth_user_created
--   function search_path is mutable
--   anon/authenticated/service_role can EXECUTE the trigger function directly
--
-- This migration preserves signup -> profile behavior while removing the
-- exposed SECURITY DEFINER RPC surface and pinning search_path.
-- =========================================================

begin;

do $preflight$
declare
  v_trigger_count integer;
  v_security_definer boolean;
begin
  if to_regclass('auth.users') is null then
    raise exception 'AUTH_USERS_TABLE_NOT_FOUND';
  end if;

  if to_regclass('public.profiles') is null then
    raise exception 'PROFILES_TABLE_NOT_FOUND';
  end if;

  if to_regprocedure('public.handle_new_user()') is null then
    raise exception 'HANDLE_NEW_USER_FUNCTION_NOT_FOUND';
  end if;

  select p.prosecdef into v_security_definer
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname = 'handle_new_user'
    and pg_get_function_identity_arguments(p.oid) = '';

  if v_security_definer is distinct from true then
    raise exception 'HANDLE_NEW_USER_NOT_SECURITY_DEFINER';
  end if;

  select count(*) into v_trigger_count
  from pg_trigger t
  join pg_class c on c.oid = t.tgrelid
  join pg_namespace n on n.oid = c.relnamespace
  join pg_proc p on p.oid = t.tgfoid
  join pg_namespace pn on pn.oid = p.pronamespace
  where not t.tgisinternal
    and n.nspname = 'auth'
    and c.relname = 'users'
    and t.tgname = 'on_auth_user_created'
    and pn.nspname = 'public'
    and p.proname = 'handle_new_user';

  if v_trigger_count <> 1 then
    raise exception 'AUTH_USER_PROFILE_TRIGGER_BASELINE_MISMATCH';
  end if;

  if not has_function_privilege('anon', 'public.handle_new_user()', 'EXECUTE')
     or not has_function_privilege('authenticated', 'public.handle_new_user()', 'EXECUTE')
     or not has_function_privilege('service_role', 'public.handle_new_user()', 'EXECUTE') then
    raise exception 'HANDLE_NEW_USER_EXECUTE_BASELINE_MISMATCH';
  end if;
end;
$preflight$;

create or replace function public.handle_new_user()
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

commit;
