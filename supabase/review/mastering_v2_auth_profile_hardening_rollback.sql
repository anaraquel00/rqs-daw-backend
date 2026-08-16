-- =========================================================
-- RQS MASTERING V2 — AUTH PROFILE HARDENING EMERGENCY ROLLBACK
-- PRODUCTION ONLY AFTER EXPLICIT ROLLBACK AUTHORIZATION.
--
-- Restores the observed pre-hardening function ACL/search_path baseline.
-- This intentionally reintroduces the known security-advisor warnings and is
-- therefore an emergency rollback only, not the desired steady state.
-- =========================================================

begin;

do $preflight$
declare
  v_config text[];
begin
  if to_regprocedure('public.handle_new_user()') is null then
    raise exception 'ROLLBACK_HANDLE_NEW_USER_MISSING';
  end if;

  select p.proconfig into v_config
  from pg_proc p
  join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public'
    and p.proname='handle_new_user'
    and pg_get_function_identity_arguments(p.oid)='';

  if v_config is distinct from array['search_path=""']::text[] then
    raise exception 'ROLLBACK_UNEXPECTED_HANDLE_NEW_USER_SEARCH_PATH: %', v_config;
  end if;

  if has_function_privilege('anon','public.handle_new_user()','EXECUTE')
     or has_function_privilege('authenticated','public.handle_new_user()','EXECUTE')
     or has_function_privilege('service_role','public.handle_new_user()','EXECUTE') then
    raise exception 'ROLLBACK_HANDLE_NEW_USER_ALREADY_EXPOSED';
  end if;
end;
$preflight$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
as $function$
begin
  insert into public.profiles (id, email, role, completed_masters)
  values (new.id, new.email, 'free', 0);
  return new;
end;
$function$;

grant execute on function public.handle_new_user()
to public, anon, authenticated, service_role;

commit;
