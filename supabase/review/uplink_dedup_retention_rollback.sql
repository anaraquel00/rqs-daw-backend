-- =========================================================
-- RQS UPLINK DEDUP RETENTION V1
-- PROPOSED ROLLBACK - REVIEW ONLY
-- Unschedules only the exact candidate job. Deleted rows are not restored.
-- =========================================================

begin;

do $preflight$
declare
  v_expected_command constant text :=
    'delete from public.rqs_uplink_click_dedup where last_counted_at < statement_timestamp() - interval ''48 hours'';';
begin
  if current_user <> 'postgres' then
    raise exception 'RETENTION_OWNER_MUST_BE_POSTGRES';
  end if;

  if to_regclass('cron.job') is null
     or to_regprocedure('cron.unschedule(text)') is null then
    raise exception 'PG_CRON_API_MISSING';
  end if;

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
    raise exception 'RETENTION_JOB_ROLLBACK_PREFLIGHT_FAILED';
  end if;
end;
$preflight$;

do $unschedule$
begin
  if not cron.unschedule('rqs-uplink-dedup-retention-daily') then
    raise exception 'RETENTION_JOB_UNSCHEDULE_FAILED';
  end if;
end;
$unschedule$;

do $postflight$
begin
  if exists (
    select 1
    from cron.job
    where jobname = 'rqs-uplink-dedup-retention-daily'
  ) then
    raise exception 'RETENTION_JOB_ROLLBACK_POSTFLIGHT_FAILED';
  end if;
end;
$postflight$;

commit;
