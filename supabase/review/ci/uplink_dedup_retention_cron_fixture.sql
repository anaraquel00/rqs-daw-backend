-- Ephemeral GitHub Actions fixture for the retention source candidate.
-- This simulates only the pg_cron catalog/API surface used by the review SQL.
-- It must never target Supabase or any persistent database.

create schema cron;
create sequence cron.jobid_seq;

create table cron.job (
  jobid bigint primary key default nextval('cron.jobid_seq'),
  schedule text not null,
  command text not null,
  nodename text not null default 'localhost',
  nodeport integer not null default 5432,
  database text not null default current_database(),
  username text not null default current_user,
  active boolean not null default true,
  jobname text not null unique
);

create table cron.job_run_details (
  jobid bigint not null,
  status text,
  start_time timestamptz,
  end_time timestamptz,
  return_message text
);

create function cron.schedule(
  job_name text,
  schedule text,
  command text
)
returns bigint
language plpgsql
as $fixture$
declare
  v_jobid bigint;
begin
  insert into cron.job as j (
    jobname,
    schedule,
    command,
    database,
    username
  ) values (
    job_name,
    schedule,
    command,
    current_database(),
    current_user
  )
  on conflict (jobname) do update
  set
    schedule = excluded.schedule,
    command = excluded.command,
    database = excluded.database,
    username = excluded.username
  returning j.jobid into v_jobid;

  return v_jobid;
end;
$fixture$;

create function cron.unschedule(job_name text)
returns boolean
language plpgsql
as $fixture$
declare
  v_deleted bigint;
begin
  delete from cron.job
  where jobname = job_name;

  get diagnostics v_deleted = row_count;
  return v_deleted = 1;
end;
$fixture$;
