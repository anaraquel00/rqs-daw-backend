-- =========================================================
-- RQS UPLINK DEDUP RETENTION V1
-- READ-ONLY AUDIT - AGGREGATES ONLY; NEVER PRINTS FINGERPRINT HASHES
-- =========================================================

select
  current_database() as database_name,
  current_user as audit_role,
  statement_timestamp() as audited_at;

select extname, extversion
from pg_extension
where extname = 'pg_cron';

select
  case
    when exists (
      select 1
      from pg_extension
      where extname = 'pg_cron'
    ) then 'PG_CRON = PRESENT'
    else 'PG_CRON = ABSENT'
  end as pg_cron_status,
  case
    when to_regclass('cron.job') is not null
      then 'CRON_JOB = AVAILABLE'
    else 'CRON_JOB = ABSENT'
  end as cron_job_catalog_status,
  case
    when to_regclass('cron.job_run_details') is not null
      then 'CRON_JOB_RUN_DETAILS = AVAILABLE'
    else 'CRON_JOB_RUN_DETAILS = ABSENT'
  end as cron_run_catalog_status;

-- Dynamic catalog reads let this same audit run before pg_cron is enabled.
-- They create no objects and never mutate scheduler state.
do $audit_cron_job$
declare
  v_job record;
  v_found boolean := false;
begin
  if to_regclass('cron.job') is null then
    raise notice 'CRON_JOB_METADATA = UNAVAILABLE';
  else
    for v_job in execute $query$
      select
        jobid,
        jobname,
        schedule,
        command,
        database,
        username,
        active
      from cron.job
      where jobname = 'rqs-uplink-dedup-retention-daily'
    $query$
    loop
      v_found := true;
      raise notice
        'CRON_JOB_METADATA jobid=% jobname=% schedule=% command=% database=% username=% active=%',
        v_job.jobid,
        v_job.jobname,
        v_job.schedule,
        v_job.command,
        v_job.database,
        v_job.username,
        v_job.active;
    end loop;

    if not v_found then
      raise notice 'CRON_JOB_METADATA = JOB_NOT_FOUND';
    end if;
  end if;
end;
$audit_cron_job$;

do $audit_cron_runs$
declare
  v_run record;
  v_found boolean := false;
begin
  if to_regclass('cron.job') is null
     or to_regclass('cron.job_run_details') is null then
    raise notice 'CRON_JOB_RUN_DETAILS = UNAVAILABLE';
  else
    for v_run in execute $query$
      select
        jobid,
        status,
        start_time,
        end_time,
        return_message
      from cron.job_run_details
      where jobid in (
        select jobid
        from cron.job
        where jobname = 'rqs-uplink-dedup-retention-daily'
      )
      order by start_time desc
      limit 20
    $query$
    loop
      v_found := true;
      raise notice
        'CRON_JOB_RUN jobid=% status=% start_time=% end_time=% return_message=%',
        v_run.jobid,
        v_run.status,
        v_run.start_time,
        v_run.end_time,
        v_run.return_message;
    end loop;

    if not v_found then
      raise notice 'CRON_JOB_RUN_DETAILS = NO_MATCHING_RUNS';
    end if;
  end if;
end;
$audit_cron_runs$;

select
  count(*) as total_rows,
  count(*) filter (
    where last_counted_at
      < statement_timestamp() - interval '48 hours'
  ) as rows_older_than_48h,
  count(*) filter (
    where last_counted_at
      >= statement_timestamp() - interval '48 hours'
  ) as rows_within_48h,
  min(last_counted_at) as oldest_counted_at,
  max(last_counted_at) as newest_counted_at
from public.rqs_uplink_click_dedup;

select
  pg_size_pretty(
    pg_total_relation_size('public.rqs_uplink_click_dedup')
  ) as dedup_total_size;

select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename = 'rqs_uplink_click_dedup'
order by indexname;

explain (costs true, verbose true, format text)
delete from public.rqs_uplink_click_dedup
where last_counted_at
  < statement_timestamp() - interval '48 hours';

select
  c.relrowsecurity,
  c.relforcerowsecurity
from pg_class as c
where c.oid = 'public.rqs_uplink_click_dedup'::regclass;

select grantee, privilege_type
from information_schema.table_privileges
where table_schema = 'public'
  and table_name = 'rqs_uplink_click_dedup'
order by grantee, privilege_type;

select
  count(*) as uplink_count,
  coalesce(sum(clicks), 0) as clicks,
  coalesce(sum(source_instagram), 0) as source_instagram,
  coalesce(sum(source_tiktok), 0) as source_tiktok,
  coalesce(sum(source_facebook), 0) as source_facebook,
  coalesce(sum(source_youtube), 0) as source_youtube,
  coalesce(sum(source_direct), 0) as source_direct
from public.rqs_uplinks;

select
  count(*) as profile_count,
  coalesce(sum(monthly_clicks), 0) as monthly_clicks,
  coalesce(sum(click_quota), 0) as click_quota
from public.profiles;

select pg_get_functiondef(
  'public.increment_uplink_clicks(uuid,text,text)'::regprocedure
) as tracking_rpc_definition;
