-- =========================================================
-- RQS UPLINK TRACKING SECURITY V3.2
-- PROPOSED MIGRATION — REVIEW ONLY
-- DO NOT RUN IN PRODUCTION WITHOUT APPROVAL AND BACKUP
-- =========================================================

begin;

-- =========================================================
-- 0. FAIL-CLOSED PREFLIGHT
--
-- This migration deliberately does not change click_quota or its default.
-- Existing product configuration remains authoritative.
-- =========================================================

do $preflight$
begin
  if to_regprocedure(
    'public.increment_uplink_clicks(uuid,text,uuid)'
  ) is null then
    raise exception 'LEGACY_RPC_NOT_FOUND';
  end if;

  if to_regclass('public.rqs_uplink_click_dedup') is not null then
    raise exception 'DEDUP_TABLE_ALREADY_EXISTS';
  end if;

  if not exists (
    select 1
    from pg_class as c
    join pg_namespace as n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'rqs_uplinks'
      and c.relkind in ('r', 'p')
      and c.relrowsecurity
  ) then
    raise exception 'RQS_UPLINKS_RLS_NOT_ENABLED';
  end if;

  if not exists (
    select 1
    from pg_policies as p
    where p.schemaname = 'public'
      and p.tablename = 'rqs_uplinks'
      and p.policyname = 'Enable read access for all users'
      and p.cmd = 'SELECT'
      and 'public' = any(p.roles)
  ) then
    raise exception 'EXPECTED_PUBLIC_SELECT_POLICY_NOT_FOUND';
  end if;

  if exists (
    select 1
    from pg_policies as p
    where p.schemaname = 'public'
      and p.tablename = 'rqs_uplinks'
      and p.cmd = 'SELECT'
      and p.policyname <> 'Enable read access for all users'
  ) then
    raise exception 'UNEXPECTED_RQS_UPLINKS_SELECT_POLICY';
  end if;

  if exists (
    select 1
    from public.profiles as p
    where p.role is null
       or p.role::text not in ('free', 'premium')
  ) then
    raise exception 'UNSUPPORTED_OR_MISSING_PROFILE_ROLE';
  end if;

  if exists (
    select 1
    from public.profiles as p
    where p.monthly_clicks is null
       or p.click_quota is null
       or (p.role::text = 'free' and p.click_quota <= 0)
  ) then
    raise exception 'INVALID_PROFILE_CLICK_COUNTERS';
  end if;

  if exists (
    select 1
    from public.rqs_uplinks as u
    where u.clicks is null
       or u.source_instagram is null
       or u.source_tiktok is null
       or u.source_facebook is null
       or u.source_youtube is null
       or u.source_direct is null
  ) then
    raise exception 'NULL_UPLINK_COUNTERS_REQUIRE_REVIEW';
  end if;
end;
$preflight$;

-- =========================================================
-- 1. CLOSE THE LEGACY ATTACK SURFACE FIRST
-- =========================================================

revoke all
on function public.increment_uplink_clicks(uuid, text, uuid)
from public, anon, authenticated, service_role;

-- =========================================================
-- 2. DISTRIBUTED DEDUPLICATION
--
-- Only a salted SHA-256 fingerprint is stored. Raw client addresses and
-- user-agent strings must never be persisted in this table.
-- =========================================================

create table public.rqs_uplink_click_dedup (
  link_id uuid not null
    references public.rqs_uplinks(id)
    on delete cascade,
  fingerprint_hash text not null
    check (fingerprint_hash ~ '^[0-9a-f]{64}$'),
  last_counted_at timestamptz not null,
  primary key (link_id, fingerprint_hash)
);

create index rqs_uplink_click_dedup_retention_idx
on public.rqs_uplink_click_dedup(link_id, last_counted_at);

alter table public.rqs_uplink_click_dedup enable row level security;

revoke all
on table public.rqs_uplink_click_dedup
from public, anon, authenticated;

grant select, insert, update, delete
on table public.rqs_uplink_click_dedup
to service_role;

-- =========================================================
-- 3. SERVICE-ROLE-ONLY ATOMIC RPC
--
-- Returns true when counters were incremented.
-- Returns false when the same fingerprint was counted for this link during
-- the preceding rolling 60 seconds.
-- =========================================================

create function public.increment_uplink_clicks(
  link_id uuid,
  source_col text,
  request_fingerprint text
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_user_id uuid;
  v_role text;
  v_monthly_clicks bigint;
  v_click_quota bigint;
  v_now timestamptz;
  v_inserted integer;
begin
  if source_col is null
     or source_col not in (
       'source_instagram',
       'source_tiktok',
       'source_facebook',
       'source_youtube',
       'source_direct'
     ) then
    raise exception 'INVALID_SOURCE';
  end if;

  if request_fingerprint is null
     or request_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'INVALID_FINGERPRINT';
  end if;

  select u.user_id
    into v_user_id
  from public.rqs_uplinks as u
  where u.id = link_id
  for no key update;

  if not found or v_user_id is null then
    raise exception 'UPLINK_NOT_FOUND';
  end if;

  -- Evaluate wall-clock time only after the Uplink row lock is acquired. This
  -- avoids using a stale statement start time after a concurrent caller wait.
  v_now := clock_timestamp();

  insert into public.rqs_uplink_click_dedup as dedup (
    link_id,
    fingerprint_hash,
    last_counted_at
  ) values (
    link_id,
    request_fingerprint,
    v_now
  )
  on conflict (link_id, fingerprint_hash) do update
  set last_counted_at = excluded.last_counted_at
  where dedup.last_counted_at
        <= excluded.last_counted_at - interval '60 seconds'
  returning 1 into v_inserted;

  if v_inserted is null then
    return false;
  end if;

  select
    p.role::text,
    p.monthly_clicks,
    p.click_quota
  into
    v_role,
    v_monthly_clicks,
    v_click_quota
  from public.profiles as p
  where p.id = v_user_id
  for update;

  if not found then
    raise exception 'PROFILE_NOT_FOUND';
  end if;

  if v_role is null then
    raise exception 'PROFILE_ROLE_MISSING';
  end if;
  if v_monthly_clicks is null then
    raise exception 'MONTHLY_CLICKS_MISSING';
  end if;
  if v_click_quota is null then
    raise exception 'CLICK_QUOTA_MISSING';
  end if;
  if v_role not in ('free', 'premium') then
    raise exception 'INVALID_PROFILE_ROLE';
  end if;

  if v_role = 'free' and v_monthly_clicks >= v_click_quota then
    raise exception 'CLICK_QUOTA_EXCEEDED';
  end if;

  update public.rqs_uplinks
  set
    clicks = clicks + 1,
    source_instagram = source_instagram +
      case when source_col = 'source_instagram' then 1 else 0 end,
    source_tiktok = source_tiktok +
      case when source_col = 'source_tiktok' then 1 else 0 end,
    source_facebook = source_facebook +
      case when source_col = 'source_facebook' then 1 else 0 end,
    source_youtube = source_youtube +
      case when source_col = 'source_youtube' then 1 else 0 end,
    source_direct = source_direct +
      case when source_col = 'source_direct' then 1 else 0 end
  where id = link_id;

  if not found then
    raise exception 'UPLINK_UPDATE_FAILED';
  end if;

  update public.profiles
  set monthly_clicks = monthly_clicks + 1
  where id = v_user_id;

  if not found then
    raise exception 'PROFILE_UPDATE_FAILED';
  end if;

  -- Opportunistic cleanup bounds storage for active links. A scheduled global
  -- cleanup is still required for inactive links; see UPLINK_ABUSE_PROTECTION.
  delete from public.rqs_uplink_click_dedup as d
  where d.link_id = $1
    and d.last_counted_at < v_now - interval '48 hours';

  return true;
end;
$function$;

revoke all
on function public.increment_uplink_clicks(uuid, text, text)
from public, anon, authenticated, service_role;

grant execute
on function public.increment_uplink_clicks(uuid, text, text)
to service_role;

-- =========================================================
-- 4. OWNER-ONLY READ POLICY
--
-- Public table-wide SELECT is removed. Authenticated owners retain access to
-- their own records. The public router reads server-side as service_role.
-- =========================================================

drop policy if exists "Enable read access for all users"
on public.rqs_uplinks;

drop policy if exists "Owners can read own uplinks"
on public.rqs_uplinks;

create policy "Owners can read own uplinks"
on public.rqs_uplinks
for select
to authenticated
using ((select auth.uid()) = user_id);

-- =========================================================
-- 5. REMOVE THE LEGACY SIGNATURE
--
-- DROP without CASCADE fails safely if a database dependency still exists.
-- External repository consumers must be audited before execution.
-- =========================================================

drop function public.increment_uplink_clicks(uuid, text, uuid);

commit;
