-- =========================================================
-- RQS UPLINK TRACKING SECURITY V3
-- SAFE ROLLBACK / TRACKING DISABLE — REVIEW ONLY
--
-- This rollback deliberately DOES NOT restore the vulnerable legacy RPC,
-- public EXECUTE grants, or public table-wide SELECT.
-- Deploy index.rollback-safe.ts before running this script.
-- =========================================================

begin;

-- Disable and remove the V3 tracking RPC. Dynamic SQL tolerates a failed or
-- only partially applied migration.
do $v3_rpc$
begin
  if to_regprocedure(
    'public.increment_uplink_clicks(uuid,text,text)'
  ) is not null then
    execute
      'revoke all on function '
      || 'public.increment_uplink_clicks(uuid,text,text) '
      || 'from public, anon, authenticated, service_role';
  end if;
end;
$v3_rpc$;

drop function if exists
public.increment_uplink_clicks(uuid, text, text);

-- Defense in depth: if the legacy signature exists for any reason, keep every
-- application role unable to execute it. Never recreate it in a rollback.
do $rollback$
begin
  if to_regprocedure(
    'public.increment_uplink_clicks(uuid,text,uuid)'
  ) is not null then
    execute
      'revoke all on function '
      || 'public.increment_uplink_clicks(uuid,text,uuid) '
      || 'from public, anon, authenticated, service_role';
  end if;
end;
$rollback$;

-- Preserve least-privilege reads for authenticated owners.
drop policy if exists "Enable read access for all users"
on public.rqs_uplinks;

drop policy if exists "Owners can read own uplinks"
on public.rqs_uplinks;

create policy "Owners can read own uplinks"
on public.rqs_uplinks
for select
to authenticated
using ((select auth.uid()) = user_id);

-- The deduplication table is intentionally retained to avoid destructive data
-- loss during an emergency rollback. If it exists, keep it inaccessible to
-- public roles. Dynamic SQL makes this safe after a partially applied change.
do $dedup$
begin
  if to_regclass('public.rqs_uplink_click_dedup') is not null then
    execute
      'revoke all on table public.rqs_uplink_click_dedup '
      || 'from public, anon, authenticated';
  end if;
end;
$dedup$;

commit;
