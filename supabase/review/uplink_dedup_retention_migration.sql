-- =========================================================
-- RQS UPLINK DEDUP RETENTION V1
-- PROPOSED MIGRATION - REVIEW ONLY
-- DO NOT RUN AGAINST SUPABASE WITHOUT APPROVAL, BACKUP AND PREFLIGHT
-- =========================================================

begin;

-- This source candidate adds only a daily pg_cron job. It deliberately does
-- not alter the tracking RPC, counters, tables, policies, grants or indexes.
do $preflight$
declare
  v_rpc_definition text;
begin
  if current_user <> 'postgres' then
    raise exception 'RETENTION_OWNER_MUST_BE_POSTGRES';
  end if;

  if to_regclass('public.rqs_uplink_click_dedup') is null
     or to_regclass('public.rqs_uplinks') is null
     or to_regclass('public.profiles') is null then
    raise exception 'UPLINK_RETENTION_BASELINE_TABLE_MISSING';
  end if;

  if to_regprocedure(
    'public.increment_uplink_clicks(uuid,text,text)'
  ) is null then
    raise exception 'UPLINK_RETENTION_BASELINE_RPC_MISSING';
  end if;

  if (
    select count(*)
    from pg_attribute
    where attrelid = 'public.rqs_uplink_click_dedup'::regclass
      and attnum > 0
      and not attisdropped
      and (
        (attname = 'link_id'
          and atttypid = 'uuid'::regtype
          and attnotnull)
        or (attname = 'fingerprint_hash'
          and atttypid = 'text'::regtype
          and attnotnull)
        or (attname = 'last_counted_at'
          and atttypid = 'timestamp with time zone'::regtype
          and attnotnull)
      )
  ) <> 3
     or (
       select count(*)
       from pg_attribute
       where attrelid = 'public.rqs_uplink_click_dedup'::regclass
         and attnum > 0
         and not attisdropped
     ) <> 3 then
    raise exception 'UPLINK_DEDUP_COLUMN_CONTRACT_DRIFT';
  end if;

  if not exists (
    select 1
    from pg_class as c
    where c.oid = 'public.rqs_uplink_click_dedup'::regclass
      and c.relkind in ('r', 'p')
      and c.relrowsecurity
  ) then
    raise exception 'UPLINK_DEDUP_RLS_NOT_ENABLED';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'rqs_uplink_click_dedup'
  ) then
    raise exception 'UPLINK_DEDUP_UNEXPECTED_POLICY';
  end if;

  if exists (
    select 1
    from information_schema.table_privileges
    where table_schema = 'public'
      and table_name = 'rqs_uplink_click_dedup'
      and grantee in ('PUBLIC', 'anon', 'authenticated')
  ) then
    raise exception 'UPLINK_DEDUP_BROAD_PRIVILEGE_DRIFT';
  end if;

  if (
    select count(distinct privilege_type)
    from information_schema.table_privileges
    where table_schema = 'public'
      and table_name = 'rqs_uplink_click_dedup'
      and grantee = 'service_role'
      and privilege_type in ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
  ) <> 4
     or not has_table_privilege(
       current_user,
       'public.rqs_uplink_click_dedup',
       'DELETE'
     ) then
    raise exception 'UPLINK_DEDUP_AUTHORIZED_DELETE_PRIVILEGE_MISSING';
  end if;

  select regexp_replace(
           lower(pg_get_functiondef(
             'public.increment_uplink_clicks(uuid,text,text)'::regprocedure
           )),
           '[[:space:]]+',
           ' ',
           'g'
         )
    into v_rpc_definition;

  if position(
       'delete from public.rqs_uplink_click_dedup as d where d.link_id = $1 and d.last_counted_at < v_now - interval ''48 hours'';'
       in v_rpc_definition
     ) = 0 then
    raise exception 'UPLINK_OPPORTUNISTIC_RETENTION_CONTRACT_DRIFT';
  end if;

  if to_regclass('cron.job') is null
     or to_regprocedure('cron.schedule(text,text,text)') is null
     or to_regprocedure('cron.unschedule(text)') is null then
    raise exception 'PG_CRON_API_MISSING';
  end if;

  if (
    select count(*)
    from information_schema.columns
    where table_schema = 'cron'
      and table_name = 'job'
      and column_name in (
        'jobid',
        'schedule',
        'command',
        'database',
        'username',
        'active',
        'jobname'
      )
  ) <> 7 then
    raise exception 'PG_CRON_JOB_CONTRACT_DRIFT';
  end if;

  if exists (
    select 1
    from cron.job
    where jobname = 'rqs-uplink-dedup-retention-daily'
  ) then
    raise exception 'RETENTION_JOB_NAME_COLLISION';
  end if;
end;
$preflight$;

select cron.schedule(
  'rqs-uplink-dedup-retention-daily',
  '0 3 * * *',
  $command$
    delete from public.rqs_uplink_click_dedup
    where last_counted_at
      < statement_timestamp() - interval '48 hours';
  $command$
);

do $postflight$
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
    raise exception 'RETENTION_JOB_POSTFLIGHT_FAILED';
  end if;
end;
$postflight$;

commit;
