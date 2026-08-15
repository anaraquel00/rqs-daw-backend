-- =========================================================
-- RQS UPLINK TRACKING SECURITY V2
-- FULL ROLLBACK — REVIEW ONLY
-- =========================================================

begin;

-- =========================================================
-- RESTORE PRE-MIGRATION QUOTA CONFIGURATION
-- =========================================================

alter table public.profiles
alter column click_quota set default 1000;

-- =========================================================
-- 1. REMOVER NOVA RPC
-- =========================================================

revoke execute
on function public.increment_uplink_clicks(uuid, text)
from public, anon, authenticated, service_role;

drop function if exists
public.increment_uplink_clicks(uuid, text);


-- =========================================================
-- 2. RESTAURAR RPC ANTIGA EXATAMENTE COMO NO AUDIT BEFORE
-- =========================================================

create or replace function public.increment_uplink_clicks(
  link_id uuid,
  source_col text,
  target_user_id uuid
)
returns void
language plpgsql
security definer
as $function$
begin
  -- Incrementa cliques no link específico e na coluna
  -- de origem correspondente dinamicamente

  execute format(
    'update rqs_uplinks
     set clicks = clicks + 1,
         %I = %I + 1
     where id = $1',
    source_col,
    source_col
  )
  using link_id;

  -- Incrementa o consumo mensal global do perfil
  update profiles
  set monthly_clicks = monthly_clicks + 1
  where id = target_user_id;
end;
$function$;


-- =========================================================
-- 3. RESTAURAR ACL BEFORE EXATAMENTE
-- =========================================================

grant execute
on function public.increment_uplink_clicks(uuid, text, uuid)
to public;

grant execute
on function public.increment_uplink_clicks(uuid, text, uuid)
to anon;

grant execute
on function public.increment_uplink_clicks(uuid, text, uuid)
to authenticated;

grant execute
on function public.increment_uplink_clicks(uuid, text, uuid)
to service_role;


-- =========================================================
-- 4. RESTAURAR SELECT PÚBLICO BEFORE
-- =========================================================

create policy "Enable read access for all users"
on public.rqs_uplinks
for select
to public
using (true);


commit;