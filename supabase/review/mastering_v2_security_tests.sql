-- =========================================================
-- RQS MASTERING V2 SECURITY — STAGING TESTS
-- MUTATING TEST FIXTURE. NEVER RUN AGAINST PRODUCTION.
-- Execute only in an isolated staging project after migration.
-- =========================================================

begin;

-- Synthetic profiles used only for staging validation.
-- Existing rows with these reserved UUIDs are a hard stop.
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

-- Run the application-facing calls as service_role so the test also proves
-- the intended EXECUTE/table-privilege surface.
set local role service_role;

-- Free user: final slot reservation succeeds.
select public.reserve_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'::uuid
);

-- Confirm exactly once.
select public.confirm_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'::uuid
);

-- Second confirmation is idempotent and must return false.
select public.confirm_mastering_quota(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'::uuid
) = false as duplicate_confirm_rejected;

-- Free profile must now be exactly 3.
select completed_masters = 3 as free_completed_exactly_three
from public.profiles
where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid;

-- At 3/3 another reservation must fail closed with the expected quota error.
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

-- Premium reservation is allowed and does not consume completed_masters.
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

-- Exact table-privilege matrix: browser roles have no direct reservation DML;
-- service_role has only the DML surface required by the SECURITY INVOKER RPCs.
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

-- Cleanup fixture before commit. The transaction commits only proof of cleanup.
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

-- The expected remaining reservation fixture count is zero.
select count(*) = 0 as fixture_cleanup_pass
from public.mastering_quota_reservations
where user_id in (
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'::uuid,
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2'::uuid
);
