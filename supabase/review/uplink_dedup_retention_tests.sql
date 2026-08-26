-- =========================================================
-- RQS UPLINK DEDUP RETENTION V1
-- EPHEMERAL REGRESSION TESTS
-- Requires the base Uplink fixture/migration, the CI cron fixture and the
-- proposed retention migration. Every data mutation is rolled back.
-- =========================================================

begin;

do $job_contract$
declare
  v_expected_command constant text :=
    'delete from public.rqs_uplink_click_dedup where last_counted_at < statement_timestamp() - interval ''48 hours'';';
begin
  if (
    select count(*)
    from cron.job
    where jobname = 'rqs-uplink-dedup-retention-daily'
      and schedule = '0 3 * * *'
      and btrim(regexp_replace(
            lower(command),
            '[[:space:]]+',
            ' ',
            'g'
          )) = v_expected_command
      and database = current_database()
      and username = current_user
      and active
  ) <> 1 then
    raise exception 'TEST_FAIL: exact daily retention job is missing';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'rqs_uplink_click_dedup'
  ) then
    raise exception 'TEST_FAIL: dedup table has a broad/unexpected policy';
  end if;

  if exists (
    select 1
    from information_schema.table_privileges
    where table_schema = 'public'
      and table_name = 'rqs_uplink_click_dedup'
      and grantee in ('PUBLIC', 'anon', 'authenticated')
  ) then
    raise exception 'TEST_FAIL: application role has direct dedup privilege';
  end if;
end;
$job_contract$;

create temporary table _retention_uplink_before on commit drop as
select coalesce(
         jsonb_agg(to_jsonb(s) order by s.id),
         '[]'::jsonb
       ) as snapshot
from (
  select
    id,
    user_id,
    clicks,
    source_instagram,
    source_tiktok,
    source_facebook,
    source_youtube,
    source_direct
  from public.rqs_uplinks
) as s;

create temporary table _retention_profile_before on commit drop as
select coalesce(
         jsonb_agg(to_jsonb(s) order by s.id),
         '[]'::jsonb
       ) as snapshot
from (
  select id, role, monthly_clicks, click_quota
  from public.profiles
) as s;

create temporary table _retention_rpc_before on commit drop as
select pg_get_functiondef(
         'public.increment_uplink_clicks(uuid,text,text)'::regprocedure
       ) as definition;

create temporary table _retention_indexes_before on commit drop as
select coalesce(
         array_agg(indexdef order by indexname),
         array[]::text[]
       ) as definitions
from pg_indexes
where schemaname = 'public'
  and tablename = 'rqs_uplink_click_dedup';

insert into public.rqs_uplink_click_dedup (
  link_id,
  fingerprint_hash,
  last_counted_at
) values
  (
    '6638dcbb-5454-4b08-a634-4ca5e735b8c9',
    repeat('1', 64),
    statement_timestamp() - interval '72 hours'
  ),
  (
    '6638dcbb-5454-4b08-a634-4ca5e735b8c9',
    repeat('2', 64),
    statement_timestamp() - interval '49 hours'
  ),
  (
    '6638dcbb-5454-4b08-a634-4ca5e735b8c9',
    repeat('3', 64),
    statement_timestamp() - interval '47 hours 59 minutes'
  ),
  (
    '6638dcbb-5454-4b08-a634-4ca5e735b8c9',
    repeat('4', 64),
    statement_timestamp() - interval '1 hour'
  );

do $execute_stored_job$
declare
  v_command text;
begin
  select command
    into strict v_command
  from cron.job
  where jobname = 'rqs-uplink-dedup-retention-daily';

  execute v_command;
end;
$execute_stored_job$;

do $retention_assertions$
declare
  v_uplink_after jsonb;
  v_profile_after jsonb;
  v_indexes_after text[];
begin
  if exists (
    select 1
    from public.rqs_uplink_click_dedup
    where fingerprint_hash in (repeat('1', 64), repeat('2', 64))
  ) then
    raise exception 'TEST_FAIL: rows older than 48 hours were retained';
  end if;

  if (
    select count(*)
    from public.rqs_uplink_click_dedup
    where fingerprint_hash in (repeat('3', 64), repeat('4', 64))
  ) <> 2 then
    raise exception 'TEST_FAIL: fresh rows were deleted';
  end if;

  select coalesce(
           jsonb_agg(to_jsonb(s) order by s.id),
           '[]'::jsonb
         )
    into v_uplink_after
  from (
    select
      id,
      user_id,
      clicks,
      source_instagram,
      source_tiktok,
      source_facebook,
      source_youtube,
      source_direct
    from public.rqs_uplinks
  ) as s;

  if v_uplink_after <> (
    select snapshot from _retention_uplink_before
  ) then
    raise exception 'TEST_FAIL: Uplink counters or ownership changed';
  end if;

  select coalesce(
           jsonb_agg(to_jsonb(s) order by s.id),
           '[]'::jsonb
         )
    into v_profile_after
  from (
    select id, role, monthly_clicks, click_quota
    from public.profiles
  ) as s;

  if v_profile_after <> (
    select snapshot from _retention_profile_before
  ) then
    raise exception 'TEST_FAIL: profile counters, roles or quotas changed';
  end if;

  if pg_get_functiondef(
       'public.increment_uplink_clicks(uuid,text,text)'::regprocedure
     ) <> (select definition from _retention_rpc_before) then
    raise exception 'TEST_FAIL: tracking RPC definition changed';
  end if;

  select coalesce(
           array_agg(indexdef order by indexname),
           array[]::text[]
         )
    into v_indexes_after
  from pg_indexes
  where schemaname = 'public'
    and tablename = 'rqs_uplink_click_dedup';

  if v_indexes_after <> (
    select definitions from _retention_indexes_before
  ) then
    raise exception 'TEST_FAIL: dedup index contract changed';
  end if;
end;
$retention_assertions$;

rollback;
