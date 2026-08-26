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
  jobid,
  jobname,
  schedule,
  command,
  database,
  username,
  active
from cron.job
where jobname = 'rqs-uplink-dedup-retention-daily';

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
limit 20;

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
