-- =========================================================
-- RQS UPLINK TRACKING - TEST PLAN
-- REVIEW ONLY
-- NÃO EXECUTAR EM PRODUÇÃO SEM APROVAÇÃO
-- =========================================================

-- ---------------------------------------------------------
-- TESTE 1 - ACL nova função
-- Esperado:
-- anon = false
-- authenticated = false
-- service_role = true
-- ---------------------------------------------------------

select
  has_function_privilege(
    'anon',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as anon_can_execute,

  has_function_privilege(
    'authenticated',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as authenticated_can_execute,

  has_function_privilege(
    'service_role',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as service_role_can_execute;

-- ---------------------------------------------------------
-- TESTE 2 - source inválido
-- Esperado: INVALID_SOURCE
-- Nenhum contador alterado.
-- ---------------------------------------------------------

-- select public.increment_uplink_clicks(
--   '<TEST_LINK_UUID>'::uuid,
--   'source_invalid'
-- );

-- ---------------------------------------------------------
-- TESTE 3 - link inexistente
-- Esperado: UPLINK_NOT_FOUND
-- ---------------------------------------------------------

-- select public.increment_uplink_clicks(
--   '00000000-0000-0000-0000-000000000000'::uuid,
--   'source_direct'
-- );

-- ---------------------------------------------------------
-- TESTE 4 - source_instagram
-- Antes e depois:
-- clicks +1
-- source_instagram +1
-- demais source_* inalterados
-- monthly_clicks +1
-- ---------------------------------------------------------

-- select public.increment_uplink_clicks(
--   '<TEST_LINK_UUID>'::uuid,
--   'source_instagram'
-- );

-- ---------------------------------------------------------
-- TESTE 5 - quota excedida
-- Preparar em ambiente controlado:
-- role = free
-- monthly_clicks = click_quota
--
-- Esperado:
-- CLICK_QUOTA_EXCEEDED
-- nenhum contador alterado.
-- ---------------------------------------------------------

-- ---------------------------------------------------------
-- TESTE 6 - Premium
-- role = premium
-- monthly_clicks >= click_quota
--
-- Esperado:
-- tracking permitido.
-- ---------------------------------------------------------

-- ---------------------------------------------------------
-- TESTE 7 - Concorrência
--
-- Preparar perfil Free com:
-- click_quota - monthly_clicks = 1
--
-- Disparar várias RPCs simultâneas.
--
-- Esperado:
-- exatamente 1 sucesso
-- demais = CLICK_QUOTA_EXCEEDED
--
-- Confirmar:
-- clicks +1 total
-- monthly_clicks +1 total
-- source selecionado +1 total
-- ---------------------------------------------------------

-- ---------------------------------------------------------
-- TESTE 8 - Redirect
--
-- Mesmo se a RPC retornar:
-- CLICK_QUOTA_EXCEEDED
-- ou erro interno de tracking,
--
-- o rqs-router deve continuar retornando redirect 302.
-- ---------------------------------------------------------