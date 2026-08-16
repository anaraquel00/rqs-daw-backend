-- =========================================================
-- RQS MASTERING V2 SECURITY — STAGING / CI TESTS
-- MUTATING TEST FIXTURE. NEVER RUN AGAINST PRODUCTION.
-- Execute only in isolated staging after migration.
-- =========================================================

begin;

-- Browser roles must no longer have direct profile write authority.
do $client_profile_acl$
begin
  if has_table_privilege('authenticated', 'public.profiles', 'INSERT')
     or has_table_privilege('authenticated', 'public.profiles', 'UPDATE')
     or has_table_privilege('authenticated', 'public.profiles', 'DELETE')
     or has_table_privilege('authenticated', 'public.profiles', 'TRUNCATE')
     or has_column_privilege('authenticated', 'public.profiles', 'role', 'UPDATE')
     or has_column_privilege('authenticated', 'public.profiles', 'completed_masters', 'UPDATE') then
    raise exception 'AUTHENTICATED_PROFILE_WRITE_AUTHORITY_NOT_RETIRED';
  end if;

  if has_table_privilege('anon', 'public.profiles', 'INSERT')
     or has_table_privilege('anon', 'public.profiles', 'UPDATE')
     or has_table_privilege('anon', 'public.profiles', 'DELETE')
     or has_table_privilege('anon', 'public.profiles', 'TRUNCATE') then
    raise exception 'ANON_PROFILE_WRITE_AUTHORITY_NOT_RETIRED';
  end if;

  if not has_table_privilege('authenticated', 'public.profiles', 'SELECT') then
    raise exception 'AUTHENTICATED_PROFILE_READ_MISSING';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'profiles' and cmd = 'UPDATE'
  ) then
    raise exception 'PROFILE_UPDATE_POLICY_STILL_PRESENT';
  end if;
end;
$client_profile_acl$;

-- Synthetic profiles used only for staging/CI validation.
do $preflight$
begin
  if exists (
    select 1 from public.profiles
    where id in (
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid
    )
  ) then
    raise exception 'MASTERING_STAGING_FIXTURE_ALREADY_EXISTS';
  end if;
end;
$preflight$;

insert into public.profiles (id, role, completed_masters)
values
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid, 'free', 2),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid, 'premium', 999);

-- Prove actual authenticated UPDATE is denied, not only metadata claims.
set local role authenticated;
select set_config('request.jwt.claim.sub', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1', true);

do $browser_update_denied$
begin
  begin
    update public.profiles
    set role = 'premium'
    where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid;
    raise exception 'AUTHENTICATED_ROLE_UPDATE_UNEXPECTEDLY_SUCCEEDED';
  exception
    when insufficient_privilege then
      null;
  end;
end;
$browser_update_denied$;

reset role;

-- Application-facing quota calls execute only through service_role.
set local role service_role;

select public.reserve_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'::uuid
);

select public.confirm_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'::uuid
);

select public.confirm_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'::uuid
) = false as duplicate_confirm_rejected;

select completed_masters = 3 as free_completed_exactly_three
from public.profiles
where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid;

do $quota_exhausted$
begin
  begin
    perform public.reserve_mastering_quota(
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
      'cccccccc-cccc-4ccc-8ccc-ccccccccccc3'::uuid
    );
    raise exception 'EXPECTED_MASTERING_QUOTA_EXCEEDED';
  exception
    when sqlstate 'P0001' then
      if sqlerrm <> 'MASTERING_QUOTA_EXCEEDED' then
        raise;
      end if;
  end;
end;
$quota_exhausted$;

select public.reserve_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc2'::uuid
);

select public.confirm_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc2'::uuid
);

select completed_masters = 999 as premium_completed_unchanged
from public.profiles
where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid;

reset role;

do $privilege_matrix$
begin
  if has_table_privilege('anon', 'public.mastering_quota_reservations', 'SELECT')
     or has_table_privilege('anon', 'public.mastering_quota_reservations', 'INSERT')
     or has_table_privilege('anon', 'public.mastering_quota_reservations', 'UPDATE')
     or has_table_privilege('anon', 'public.mastering_quota_reservations', 'DELETE') then
    raise exception 'ANON_MASTERING_RESERVATION_DML_NOT_REVOKED';
  end if;

  if has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'SELECT')
     or has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'INSERT')
     or has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'UPDATE')
     or has_table_privilege('authenticated', 'public.mastering_quota_reservations', 'DELETE') then
    raise exception 'AUTHENTICATED_MASTERING_RESERVATION_DML_NOT_REVOKED';
  end if;

  if not has_table_privilege('service_role', 'public.mastering_quota_reservations', 'SELECT')
     or not has_table_privilege('service_role', 'public.mastering_quota_reservations', 'INSERT')
     or not has_table_privilege('service_role', 'public.mastering_quota_reservations', 'UPDATE')
     or not has_table_privilege('service_role', 'public.mastering_quota_reservations', 'DELETE') then
    raise exception 'SERVICE_ROLE_MASTERING_RESERVATION_DML_MISSING';
  end if;
end;
$privilege_matrix$;

-- Cleanup fixture before commit.
delete from public.mastering_quota_reservations
where user_id in (
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid
);

delete from public.profiles
where id in (
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid
);

commit;

select count(*) = 0 as fixture_cleanup_pass
from public.mastering_quota_reservations
where user_id in (
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid
);
