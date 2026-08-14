-- =========================================================
-- RQS UPLINK TRACKING - PROPOSED MIGRATION
-- REVIEW ONLY - DO NOT RUN BEFORE APPROVAL
-- =========================================================

begin;

-- ---------------------------------------------------------
-- 1. Fechar a assinatura antiga vulnerável
-- ---------------------------------------------------------

revoke execute
on function public.increment_uplink_clicks(uuid, text, uuid)
from public, anon, authenticated;

-- ---------------------------------------------------------
-- 2. Criar nova RPC mínima
-- ---------------------------------------------------------

create or replace function public.increment_uplink_clicks(
  link_id uuid,
  source_col text
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_user_id uuid;
  v_role text;
  v_monthly_clicks integer;
  v_click_quota integer;
begin

  -- Allowlist de origem
  if source_col not in (
    'source_instagram',
    'source_tiktok',
    'source_facebook',
    'source_youtube',
    'source_direct'
  ) then
    raise exception 'INVALID_SOURCE';
  end if;

  -- Descobre o dono do link internamente
  select u.user_id
  into v_user_id
  from public.rqs_uplinks u
  where u.id = link_id;

  if not found then
    raise exception 'UPLINK_NOT_FOUND';
  end if;

  -- Lock do perfil: evita corrida de quota
  select
    p.role,
    coalesce(p.monthly_clicks, 0),
    coalesce(p.click_quota, 1000)
  into
    v_role,
    v_monthly_clicks,
    v_click_quota
  from public.profiles p
  where p.id = v_user_id
  for update;

  if not found then
    raise exception 'PROFILE_NOT_FOUND';
  end if;

  -- Free respeita quota; premium não
  if
    coalesce(v_role, 'free') <> 'premium'
    and v_monthly_clicks >= v_click_quota
  then
    raise exception 'CLICK_QUOTA_EXCEEDED';
  end if;

  -- Atualiza click + source específico
  update public.rqs_uplinks
  set
    clicks =
      coalesce(clicks, 0) + 1,

    source_instagram =
      coalesce(source_instagram, 0)
      + case
          when source_col = 'source_instagram'
          then 1 else 0
        end,

    source_tiktok =
      coalesce(source_tiktok, 0)
      + case
          when source_col = 'source_tiktok'
          then 1 else 0
        end,

    source_facebook =
      coalesce(source_facebook, 0)
      + case
          when source_col = 'source_facebook'
          then 1 else 0
        end,

    source_youtube =
      coalesce(source_youtube, 0)
      + case
          when source_col = 'source_youtube'
          then 1 else 0
        end,

    source_direct =
      coalesce(source_direct, 0)
      + case
          when source_col = 'source_direct'
          then 1 else 0
        end

  where id = link_id;

  if not found then
    raise exception 'UPLINK_UPDATE_FAILED';
  end if;

  -- Incrementa consumo mensal
  update public.profiles
  set monthly_clicks =
    coalesce(monthly_clicks, 0) + 1
  where id = v_user_id;

end;
$$;

-- ---------------------------------------------------------
-- 3. ACL da nova assinatura
-- ---------------------------------------------------------

revoke execute
on function public.increment_uplink_clicks(uuid, text)
from public, anon, authenticated;

grant execute
on function public.increment_uplink_clicks(uuid, text)
to service_role;

commit;

-- ---------------------------------------------------------
-- 4. REMOÇÃO DA FUNÇÃO ANTIGA
-- EXECUTAR SOMENTE APÓS CONFIRMAR ZERO DEPENDÊNCIAS
-- ---------------------------------------------------------

-- drop function public.increment_uplink_clicks(uuid, text, uuid);