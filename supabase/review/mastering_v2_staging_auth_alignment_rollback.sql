-- RQS MASTERING V2 — ISOLATED STAGING AUTH ALIGNMENT ROLLBACK
-- STAGING ONLY. Safe only before a staging Auth test identity is retained.

begin;

do $preflight$
begin
  if (select count(*) from auth.users) <> 0 then
    raise exception 'STAGING_AUTH_ALIGNMENT_ROLLBACK_BLOCKED_USERS_EXIST';
  end if;

  if to_regprocedure('public.handle_new_user()') is null then
    raise exception 'STAGING_HANDLE_NEW_USER_MISSING';
  end if;
end;
$preflight$;

drop trigger if exists on_auth_user_created on auth.users;
drop function public.handle_new_user();

commit;
