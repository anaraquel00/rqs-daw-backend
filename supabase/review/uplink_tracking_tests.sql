-- =========================================================
-- RQS UPLINK TRACKING SECURITY V3 — POST-MIGRATION TESTS
--
-- Run in Supabase SQL Editor only after approved migration.
-- All controlled data mutations are enclosed in one transaction and rolled
-- back. Any failed assertion aborts the script.
-- =========================================================

begin;

-- =========================================================
-- 1. CONTRACT AND ACL ASSERTIONS
-- =========================================================

do $acl$
begin
  if to_regprocedure(
    'public.increment_uplink_clicks(uuid,text,uuid)'
  ) is not null then
    raise exception 'TEST_FAIL: legacy RPC still exists';
  end if;

  if to_regprocedure(
    'public.increment_uplink_clicks(uuid,text,text)'
  ) is null then
    raise exception 'TEST_FAIL: V3 RPC is missing';
  end if;

  if has_function_privilege(
    'anon',
    'public.increment_uplink_clicks(uuid,text,text)',
    'EXECUTE'
  ) then
    raise exception 'TEST_FAIL: anon can execute V3 RPC';
  end if;

  if has_function_privilege(
    'authenticated',
    'public.increment_uplink_clicks(uuid,text,text)',
    'EXECUTE'
  ) then
    raise exception 'TEST_FAIL: authenticated can execute V3 RPC';
  end if;

  if not has_function_privilege(
    'service_role',
    'public.increment_uplink_clicks(uuid,text,text)',
    'EXECUTE'
  ) then
    raise exception 'TEST_FAIL: service_role cannot execute V3 RPC';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'rqs_uplinks'
      and 'public' = any(roles)
      and cmd = 'SELECT'
  ) then
    raise exception 'TEST_FAIL: public SELECT policy still exists';
  end if;

  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'rqs_uplinks'
      and policyname = 'Owners can read own uplinks'
      and 'authenticated' = any(roles)
      and cmd = 'SELECT'
  ) then
    raise exception 'TEST_FAIL: owner-only SELECT policy is missing';
  end if;

  if (
    select count(*)
    from pg_policies
    where schemaname = 'public'
      and tablename = 'rqs_uplinks'
      and cmd = 'SELECT'
  ) <> 1 then
    raise exception 'TEST_FAIL: unexpected additional SELECT policy exists';
  end if;

  if exists (
    select 1
    from information_schema.routine_privileges
    where routine_schema = 'public'
      and routine_name = 'increment_uplink_clicks'
      and grantee in ('PUBLIC', 'anon', 'authenticated')
      and privilege_type = 'EXECUTE'
  ) then
    raise exception 'TEST_FAIL: public application role has explicit EXECUTE';
  end if;
end;
$acl$;

-- =========================================================
-- 2. CONTROLLED FIXTURE FROM THE APPROVED TEST LINK
-- =========================================================

create temporary table _uplink_test_snapshot
on commit drop
as
select
  u.id as link_id,
  u.user_id,
  u.clicks,
  u.source_instagram,
  u.source_tiktok,
  u.source_facebook,
  u.source_youtube,
  u.source_direct,
  p.role,
  p.monthly_clicks,
  p.click_quota
from public.rqs_uplinks as u
join public.profiles as p on p.id = u.user_id
where u.custom_slug = 'flower-newworld';

do $fixture$
begin
  if (select count(*) from _uplink_test_snapshot) <> 1 then
    raise exception 'TEST_FAIL: expected exactly one flower-newworld fixture';
  end if;
end;
$fixture$;

-- =========================================================
-- 3. INVALID INPUTS AND ATOMICITY
-- =========================================================

do $invalid_source$
declare
  v_link_id uuid := (select link_id from _uplink_test_snapshot);
begin
  begin
    perform public.increment_uplink_clicks(
      v_link_id,
      null,
      repeat('a', 64)
    );
    raise exception 'TEST_FAIL: NULL source was accepted';
  exception when others then
    if position('INVALID_SOURCE' in sqlerrm) = 0 then
      raise;
    end if;
  end;

  begin
    perform public.increment_uplink_clicks(
      v_link_id,
      'source_fake',
      repeat('b', 64)
    );
    raise exception 'TEST_FAIL: invalid source was accepted';
  exception when others then
    if position('INVALID_SOURCE' in sqlerrm) = 0 then
      raise;
    end if;
  end;

  begin
    perform public.increment_uplink_clicks(
      v_link_id,
      'source_direct',
      'not-a-sha256'
    );
    raise exception 'TEST_FAIL: invalid fingerprint was accepted';
  exception when others then
    if position('INVALID_FINGERPRINT' in sqlerrm) = 0 then
      raise;
    end if;
  end;

  begin
    perform public.increment_uplink_clicks(
      '00000000-0000-0000-0000-000000000000'::uuid,
      'source_direct',
      repeat('c', 64)
    );
    raise exception 'TEST_FAIL: unknown link was accepted';
  exception when others then
    if position('UPLINK_NOT_FOUND' in sqlerrm) = 0 then
      raise;
    end if;
  end;
end;
$invalid_source$;

-- =========================================================
-- 4. SUCCESS, SOURCE COUNTER AND ONE-MINUTE DEDUPLICATION
-- =========================================================

update public.profiles
set role = 'premium'
where id = (select user_id from _uplink_test_snapshot);

do $dedup$
declare
  v_link_id uuid := (select link_id from _uplink_test_snapshot);
  v_user_id uuid := (select user_id from _uplink_test_snapshot);
  v_clicks_before bigint;
  v_instagram_before bigint;
  v_monthly_before bigint;
  v_first boolean;
  v_second boolean;
begin
  select clicks, source_instagram
    into v_clicks_before, v_instagram_before
  from public.rqs_uplinks
  where id = v_link_id;

  select monthly_clicks
    into v_monthly_before
  from public.profiles
  where id = v_user_id;

  v_first := public.increment_uplink_clicks(
    v_link_id,
    'source_instagram',
    repeat('d', 64)
  );
  v_second := public.increment_uplink_clicks(
    v_link_id,
    'source_instagram',
    repeat('d', 64)
  );

  if v_first is not true or v_second is not false then
    raise exception 'TEST_FAIL: dedup return values are incorrect';
  end if;

  if (select clicks from public.rqs_uplinks where id = v_link_id)
       <> v_clicks_before + 1 then
    raise exception 'TEST_FAIL: clicks did not increase exactly once';
  end if;

  if (select source_instagram from public.rqs_uplinks where id = v_link_id)
       <> v_instagram_before + 1 then
    raise exception 'TEST_FAIL: Instagram counter did not increase once';
  end if;

  if (select monthly_clicks from public.profiles where id = v_user_id)
       <> v_monthly_before + 1 then
    raise exception 'TEST_FAIL: monthly_clicks did not increase once';
  end if;
end;
$dedup$;

-- =========================================================
-- 5. FREE QUOTA SERIALIZATION / ATOMIC FAILURE
--
-- This verifies the boundary in one session. The separate deployment runbook
-- requires a parallel multi-session test before production approval.
-- =========================================================

update public.profiles
set
  role = 'free',
  monthly_clicks = click_quota - 1
where id = (select user_id from _uplink_test_snapshot);

do $quota$
declare
  v_link_id uuid := (select link_id from _uplink_test_snapshot);
  v_user_id uuid := (select user_id from _uplink_test_snapshot);
  v_clicks_before bigint;
  v_direct_before bigint;
  v_quota integer;
begin
  select clicks, source_direct
    into v_clicks_before, v_direct_before
  from public.rqs_uplinks
  where id = v_link_id;

  select click_quota into v_quota
  from public.profiles
  where id = v_user_id;

  if public.increment_uplink_clicks(
    v_link_id,
    'source_direct',
    repeat('e', 64)
  ) is not true then
    raise exception 'TEST_FAIL: final available Free click was rejected';
  end if;

  begin
    perform public.increment_uplink_clicks(
      v_link_id,
      'source_direct',
      repeat('f', 64)
    );
    raise exception 'TEST_FAIL: over-quota click was accepted';
  exception when others then
    if position('CLICK_QUOTA_EXCEEDED' in sqlerrm) = 0 then
      raise;
    end if;
  end;

  if (select monthly_clicks from public.profiles where id = v_user_id)
       <> v_quota then
    raise exception 'TEST_FAIL: monthly quota boundary is incorrect';
  end if;

  if (select clicks from public.rqs_uplinks where id = v_link_id)
       <> v_clicks_before + 1 then
    raise exception 'TEST_FAIL: over-quota request changed clicks';
  end if;

  if (select source_direct from public.rqs_uplinks where id = v_link_id)
       <> v_direct_before + 1 then
    raise exception 'TEST_FAIL: over-quota request changed source counter';
  end if;

  if exists (
    select 1
    from public.rqs_uplink_click_dedup
    where link_id = v_link_id
      and fingerprint_hash = repeat('f', 64)
  ) then
    raise exception 'TEST_FAIL: failed tracking left a dedup row';
  end if;
end;
$quota$;

-- No controlled mutation survives this point.
rollback;

-- Expected SQL Editor result: no exception and final command ROLLBACK.
