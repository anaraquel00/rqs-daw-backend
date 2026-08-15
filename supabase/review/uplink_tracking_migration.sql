-- =========================================================
-- RQS UPLINK TRACKING SECURITY V2
-- PROPOSED MIGRATION — REVIEW ONLY
-- DO NOT RUN IN PRODUCTION WITHOUT APPROVAL
-- =========================================================

begin;

-- =========================================================
-- 0. BUSINESS RULE — TRACKING QUOTA
--
-- FREE:
--   700 tracked clicks / month
--
-- PREMIUM:
--   unlimited tracking
--
-- Redirects remain unlimited for both plans.
-- Quota exhaustion disables tracking only.
-- =========================================================

alter table public.profiles
alter column click_quota set default 700;

revoke execute
on function public.increment_uplink_clicks(uuid, text, uuid)
from public, anon, authenticated, service_role;

-- =========================================================
-- 2. NOVA RPC
--
-- Business rule:
-- FREE    -> respeita click_quota
-- PREMIUM -> ilimitado
--
-- Mesmo Premium precisa ter role/monthly_clicks/click_quota
-- preenchidos. Estado incompleto = fail closed.
-- =========================================================

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

  -- -------------------------------------------------------
  -- SOURCE: NULL também é inválido
  -- -------------------------------------------------------

  if source_col is null
     or source_col not in (
       'source_instagram',
       'source_tiktok',
       'source_facebook',
       'source_youtube',
       'source_direct'
     )
  then
    raise exception 'INVALID_SOURCE';
  end if;


  -- -------------------------------------------------------
  -- LINK
  -- O caller NÃO fornece user_id.
  -- -------------------------------------------------------

  select u.user_id
    into v_user_id
  from public.rqs_uplinks as u
  where u.id = link_id;

  if not found or v_user_id is null then
    raise exception 'UPLINK_NOT_FOUND';
  end if;


  -- -------------------------------------------------------
  -- PROFILE LOCK
  --
  -- FOR UPDATE serializa os cliques concorrentes do
  -- mesmo proprietário durante a verificação da quota.
  -- -------------------------------------------------------

  select
    p.role,
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


  -- -------------------------------------------------------
  -- FAIL CLOSED
  -- Nada de COALESCE transformando dados ausentes em acesso.
  -- -------------------------------------------------------

  if v_role is null then
    raise exception 'PROFILE_ROLE_MISSING';
  end if;

  if v_monthly_clicks is null then
    raise exception 'MONTHLY_CLICKS_MISSING';
  end if;

  if v_click_quota is null then
    raise exception 'CLICK_QUOTA_MISSING';
  end if;


  -- -------------------------------------------------------
  -- ROLE ALLOWLIST
  -- -------------------------------------------------------

  if v_role not in ('free', 'premium') then
    raise exception 'INVALID_PROFILE_ROLE';
  end if;


  -- -------------------------------------------------------
  -- QUOTA
  --
  -- FREE: aplica quota.
  -- PREMIUM: ilimitado, mas monthly_clicks continua sendo
  -- contabilizado para analytics.
  -- -------------------------------------------------------

  if v_role = 'free'
     and v_monthly_clicks >= v_click_quota
  then
    raise exception 'CLICK_QUOTA_EXCEEDED';
  end if;


  -- -------------------------------------------------------
  -- TRACKING
  --
  -- Se qualquer comando posterior falhar, a chamada inteira
  -- é revertida pela transação PostgreSQL.
  -- -------------------------------------------------------

  update public.rqs_uplinks
  set
    clicks = clicks + 1,

    source_instagram =
      source_instagram +
      case
        when source_col = 'source_instagram'
        then 1 else 0
      end,

    source_tiktok =
      source_tiktok +
      case
        when source_col = 'source_tiktok'
        then 1 else 0
      end,

    source_facebook =
      source_facebook +
      case
        when source_col = 'source_facebook'
        then 1 else 0
      end,

    source_youtube =
      source_youtube +
      case
        when source_col = 'source_youtube'
        then 1 else 0
      end,

    source_direct =
      source_direct +
      case
        when source_col = 'source_direct'
        then 1 else 0
      end

  where id = link_id;

  if not found then
    raise exception 'UPLINK_UPDATE_FAILED';
  end if;


  -- -------------------------------------------------------
  -- ACCOUNT USAGE
  -- -------------------------------------------------------

  update public.profiles
  set monthly_clicks = monthly_clicks + 1
  where id = v_user_id;

  if not found then
    raise exception 'PROFILE_UPDATE_FAILED';
  end if;

end;
$$;


-- =========================================================
-- 3. ACL DA NOVA RPC
-- =========================================================

revoke execute
on function public.increment_uplink_clicks(uuid, text)
from public, anon, authenticated;

grant execute
on function public.increment_uplink_clicks(uuid, text)
to service_role;


-- =========================================================
-- 4. SELECT PÚBLICO
--
-- Removemos leitura direta pública da tabela inteira.
-- Router utilizará service_role server-side.
-- =========================================================

drop policy if exists
"Enable read access for all users"
on public.rqs_uplinks;


-- =========================================================
-- 5. FUNÇÃO ANTIGA
--
-- NÃO executar DROP antes da verificação de dependências.
--
-- Depois de zero dependências confirmado:
--
-- drop function
-- public.increment_uplink_clicks(uuid, text, uuid);
-- =========================================================

commit;