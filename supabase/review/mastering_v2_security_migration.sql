-- =========================================================
-- RQS MASTERING V2 — PROJECT 1 SECURITY / QUOTA
-- REVIEW CANDIDATE — DO NOT RUN IN PRODUCTION WITHOUT
-- BACKUP, STAGING VALIDATION AND EXPLICIT APPROVAL
-- =========================================================

begin;

-- =========================================================
-- 0. FAIL-CLOSED PREFLIGHT
-- =========================================================

do $preflight$
declare
  v_data_type text;
begin
  if to_regclass('public.profiles') is null then
    raise exception 'PROFILES_TABLE_NOT_FOUND';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'profiles'
      and column_name = 'id'
  ) then
    raise exception 'PROFILES_ID_COLUMN_NOT_FOUND';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'profiles'
      and column_name = 'role'
  ) then
    raise exception 'PROFILES_ROLE_COLUMN_NOT_FOUND';
  end if;

  select data_type
    into v_data_type
  from information_schema.columns
  where table_schema = 'public'
    and table_name = 'profiles'
    and column_name = 'completed_masters';

  if v_data_type is null then
    raise exception 'COMPLETED_MASTERS_COLUMN_NOT_FOUND';
  end if;

  if v_data_type not in ('smallint', 'integer', 'bigint', 'numeric') then
    raise exception 'COMPLETED_MASTERS_TYPE_UNSUPPORTED: %', v_data_type;
  end if;

  if not has_table_privilege('service_role', 'public.profiles', 'SELECT')
     or not has_table_privilege('service_role', 'public.profiles', 'UPDATE') then
    raise exception 'SERVICE_ROLE_PROFILES_PRIVILEGES_MISSING';
  end if;

  -- Expected Final Beta baseline: the general browser UPDATE has already been
  -- removed, while authenticated still has the temporary column-level
  -- completed_masters UPDATE used by the old client quota path. Fail closed if
  -- this has drifted so rollback cannot accidentally restore the wrong ACL.
  if has_table_privilege('authenticated', 'public.profiles', 'UPDATE') then
    raise exception 'AUTHENTICATED_PROFILES_TABLE_UPDATE_UNEXPECTED';
  end if;

  if not has_column_privilege(
    'authenticated',
    'public.profiles',
    'completed_masters',
    'UPDATE'
  ) then
    raise exception 'AUTHENTICATED_COMPLETED_MASTERS_UPDATE_BASELINE_MISSING';
  end if;

  -- Effective anon privileges also include grants inherited through PUBLIC,
  -- so these two checks cover both anon and accidental PUBLIC exposure without
  -- treating PUBLIC as a normal login role in has_*_privilege().
  if has_table_privilege('anon', 'public.profiles', 'UPDATE')
     or has_column_privilege('anon', 'public.profiles', 'completed_masters', 'UPDATE') then
    raise exception 'PUBLIC_OR_ANON_PROFILE_UPDATE_UNEXPECTED';
  end if;

  if exists (
    select 1
    from public.profiles
    where role is null
       or role::text not in ('free', 'premium')
  ) then
    raise exception 'PROFILE_ROLE_INVALID';
  end if;

  if exists (
    select 1
    from public.profiles
    where completed_masters is null
       or completed_masters < 0
  ) then
    raise exception 'COMPLETED_MASTERS_INVALID';
  end if;

  if to_regclass('public.mastering_quota_reservations') is not null then
    raise exception 'MASTERING_QUOTA_RESERVATIONS_ALREADY_EXISTS';
  end if;

  if to_regprocedure('public.reserve_mastering_quota(uuid,uuid)') is not null
     or to_regprocedure('public.confirm_mastering_quota(uuid,uuid)') is not null
     or to_regprocedure('public.release_mastering_quota(uuid,uuid)') is not null then
    raise exception 'MASTERING_QUOTA_RPC_ALREADY_EXISTS';
  end if;
end;
$preflight$;

-- =========================================================
-- 1. RETIRE CLIENT QUOTA WRITE AUTHORITY
-- =========================================================

revoke update (completed_masters)
on table public.profiles
from authenticated;

-- Defensive no-op revokes keep the post-migration intent explicit even though
-- preflight already requires these roles to have no effective UPDATE.
revoke update (completed_masters)
on table public.profiles
from anon, public;

-- =========================================================
-- 2. RESERVATION TABLE
-- =========================================================

create table public.mastering_quota_reservations (
  id uuid primary key,
  user_id uuid not null
    references public.profiles(id)
    on delete cascade,
  counts_quota boolean not null,
  status text not null
    check (status in ('reserved', 'completed', 'released')),
  created_at timestamptz not null default clock_timestamp(),
  finalized_at timestamptz null
);

create index mastering_quota_reservations_user_status_idx
on public.mastering_quota_reservations(user_id, status, created_at);

alter table public.mastering_quota_reservations enable row level security;

revoke all
on table public.mastering_quota_reservations
from public, anon, authenticated;

grant select, insert, update, delete
on table public.mastering_quota_reservations
to service_role;

-- =========================================================
-- 3. ATOMIC RESERVATION
--
-- Free users are limited to 3 completed+reserved masters.
-- Premium users are tracked but do not consume the quota.
-- Old abandoned reservations are released after 2 hours.
-- =========================================================

create function public.reserve_mastering_quota(
  p_user_id uuid,
  p_reservation_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_role text;
  v_completed bigint;
  v_reserved bigint;
  v_counts_quota boolean;
  v_now timestamptz;
begin
  if p_user_id is null or p_reservation_id is null then
    raise exception 'MASTERING_RESERVATION_ARGUMENT_MISSING';
  end if;

  v_now := clock_timestamp();

  select
    p.role::text,
    p.completed_masters::bigint
  into
    v_role,
    v_completed
  from public.profiles as p
  where p.id = p_user_id
  for update;

  if not found then
    raise exception 'PROFILE_NOT_FOUND';
  end if;

  if v_role is null or v_role not in ('free', 'premium') then
    raise exception 'PROFILE_ROLE_INVALID';
  end if;

  if v_completed is null or v_completed < 0 then
    raise exception 'COMPLETED_MASTERS_INVALID';
  end if;

  update public.mastering_quota_reservations
  set
    status = 'released',
    finalized_at = v_now
  where user_id = p_user_id
    and status = 'reserved'
    and created_at < v_now - interval '2 hours';

  select count(*)::bigint
    into v_reserved
  from public.mastering_quota_reservations
  where user_id = p_user_id
    and status = 'reserved'
    and counts_quota;

  v_counts_quota := (v_role = 'free');

  if v_counts_quota
     and (v_completed + v_reserved) >= 3 then
    raise exception using
      errcode = 'P0001',
      message = 'MASTERING_QUOTA_EXCEEDED';
  end if;

  insert into public.mastering_quota_reservations (
    id,
    user_id,
    counts_quota,
    status,
    created_at
  ) values (
    p_reservation_id,
    p_user_id,
    v_counts_quota,
    'reserved',
    v_now
  );

  return jsonb_build_object(
    'reservation_id', p_reservation_id,
    'role', v_role,
    'completed_masters', v_completed,
    'active_reservations', v_reserved + case when v_counts_quota then 1 else 0 end,
    'counts_quota', v_counts_quota
  );
end;
$function$;

-- =========================================================
-- 4. CONFIRM SUCCESS
-- =========================================================

create function public.confirm_mastering_quota(
  p_user_id uuid,
  p_reservation_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_status text;
  v_counts_quota boolean;
begin
  if p_user_id is null or p_reservation_id is null then
    raise exception 'MASTERING_CONFIRM_ARGUMENT_MISSING';
  end if;

  -- Keep the same lock order as reserve_mastering_quota: profile first,
  -- reservation second. This avoids a profile/reservation lock-order cycle
  -- when a stale reservation is being cleaned up while another session
  -- attempts to confirm it.
  perform 1
  from public.profiles as p
  where p.id = p_user_id
  for update;

  if not found then
    raise exception 'PROFILE_NOT_FOUND';
  end if;

  select
    r.status,
    r.counts_quota
  into
    v_status,
    v_counts_quota
  from public.mastering_quota_reservations as r
  where r.id = p_reservation_id
    and r.user_id = p_user_id
  for update;

  if not found then
    raise exception 'MASTERING_RESERVATION_NOT_FOUND';
  end if;

  if v_status = 'completed' then
    return false;
  end if;

  if v_status <> 'reserved' then
    raise exception 'MASTERING_RESERVATION_NOT_ACTIVE';
  end if;

  if v_counts_quota then
    update public.profiles
    set completed_masters = completed_masters + 1
    where id = p_user_id;

    if not found then
      raise exception 'PROFILE_NOT_FOUND';
    end if;
  end if;

  update public.mastering_quota_reservations
  set
    status = 'completed',
    finalized_at = clock_timestamp()
  where id = p_reservation_id
    and user_id = p_user_id;

  return true;
end;
$function$;

-- =========================================================
-- 5. RELEASE FAILED/CANCELLED WORK
-- =========================================================

create function public.release_mastering_quota(
  p_user_id uuid,
  p_reservation_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_status text;
begin
  if p_user_id is null or p_reservation_id is null then
    raise exception 'MASTERING_RELEASE_ARGUMENT_MISSING';
  end if;

  select r.status
    into v_status
  from public.mastering_quota_reservations as r
  where r.id = p_reservation_id
    and r.user_id = p_user_id
  for update;

  if not found then
    raise exception 'MASTERING_RESERVATION_NOT_FOUND';
  end if;

  if v_status <> 'reserved' then
    return false;
  end if;

  update public.mastering_quota_reservations
  set
    status = 'released',
    finalized_at = clock_timestamp()
  where id = p_reservation_id
    and user_id = p_user_id;

  return true;
end;
$function$;

-- =========================================================
-- 6. EXECUTION SURFACE
-- =========================================================

revoke all
on function public.reserve_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

revoke all
on function public.confirm_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

revoke all
on function public.release_mastering_quota(uuid, uuid)
from public, anon, authenticated, service_role;

grant execute
on function public.reserve_mastering_quota(uuid, uuid)
to service_role;

grant execute
on function public.confirm_mastering_quota(uuid, uuid)
to service_role;

grant execute
on function public.release_mastering_quota(uuid, uuid)
to service_role;

commit;
