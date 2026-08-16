-- RQS MASTERING V2 — AUTH PROFILE CREATION AUDIT
-- READ ONLY

do $audit$
declare
  v_trigger_count integer;
  v_security_definer boolean;
  v_config text[];
begin
  if to_regprocedure('public.handle_new_user()') is null then
    raise exception 'AUDIT_HANDLE_NEW_USER_MISSING';
  end if;

  select p.prosecdef, p.proconfig
    into v_security_definer, v_config
  from pg_proc p
  join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public'
    and p.proname='handle_new_user'
    and pg_get_function_identity_arguments(p.oid)='';

  if v_security_definer is distinct from true then
    raise exception 'AUDIT_HANDLE_NEW_USER_NOT_SECURITY_DEFINER';
  end if;

  if v_config is distinct from array['search_path=""']::text[] then
    raise exception 'AUDIT_HANDLE_NEW_USER_SEARCH_PATH_NOT_PINNED: %', v_config;
  end if;

  if has_function_privilege('anon', 'public.handle_new_user()', 'EXECUTE')
     or has_function_privilege('authenticated', 'public.handle_new_user()', 'EXECUTE')
     or has_function_privilege('service_role', 'public.handle_new_user()', 'EXECUTE') then
    raise exception 'AUDIT_HANDLE_NEW_USER_BROWSER_OR_SERVICE_EXECUTE_EXPOSED';
  end if;

  select count(*) into v_trigger_count
  from pg_trigger t
  join pg_class c on c.oid=t.tgrelid
  join pg_namespace n on n.oid=c.relnamespace
  join pg_proc p on p.oid=t.tgfoid
  join pg_namespace pn on pn.oid=p.pronamespace
  where not t.tgisinternal
    and n.nspname='auth'
    and c.relname='users'
    and t.tgname='on_auth_user_created'
    and pn.nspname='public'
    and p.proname='handle_new_user';

  if v_trigger_count <> 1 then
    raise exception 'AUDIT_AUTH_PROFILE_TRIGGER_MISMATCH';
  end if;
end;
$audit$;

select
  'MASTERING_V2_AUTH_PROFILE_HARDENING_AUDIT: PASS' as result;
