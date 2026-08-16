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
