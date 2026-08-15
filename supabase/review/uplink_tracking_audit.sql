-- =========================================================
-- RQS UPLINK TRACKING - AUDIT QUERIES
-- REVIEW ONLY - NO PRODUCTION MUTATION
-- =========================================================

-- 1. Assinaturas existentes da RPC
select
  p.proname,
  pg_get_function_identity_arguments(p.oid) as args,
  p.prosecdef,
  p.proowner::regrole as owner,
  p.proconfig
from pg_proc p
join pg_namespace n
  on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'increment_uplink_clicks';

-- 2. Definição completa da RPC
select
  p.proname,
  pg_get_function_identity_arguments(p.oid) as args,
  pg_get_functiondef(p.oid)
from pg_proc p
join pg_namespace n
  on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'increment_uplink_clicks';

-- 3. ACL / EXECUTE
select
  routine_schema,
  routine_name,
  grantee,
  privilege_type
from information_schema.routine_privileges
where routine_schema = 'public'
  and routine_name = 'increment_uplink_clicks'
order by grantee;

-- 4. EXECUTE explícito da assinatura antiga
select
  has_function_privilege(
    'anon',
    'public.increment_uplink_clicks(uuid,text,uuid)',
    'EXECUTE'
  ) as old_anon_can_execute,

  has_function_privilege(
    'authenticated',
    'public.increment_uplink_clicks(uuid,text,uuid)',
    'EXECUTE'
  ) as old_authenticated_can_execute,

  has_function_privilege(
    'service_role',
    'public.increment_uplink_clicks(uuid,text,uuid)',
    'EXECUTE'
  ) as old_service_role_can_execute;

-- =========================================================
-- 5. EXECUTE explícito da NOVA assinatura
-- POST-MIGRATION ONLY
-- NÃO EXECUTAR ANTES DA MIGRAÇÃO
-- =========================================================

select
  has_function_privilege(
    'anon',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as new_anon_can_execute,

  has_function_privilege(
    'authenticated',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as new_authenticated_can_execute,

  has_function_privilege(
    'service_role',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as new_service_role_can_execute;

-- 6. Policies da rqs_uplinks
select
  policyname,
  permissive,
  roles,
  cmd,
  qual,
  with_check
from pg_policies
where schemaname = 'public'
  and tablename = 'rqs_uplinks';

-- 7. Constraint UNIQUE do custom_slug
select
  conname,
  pg_get_constraintdef(oid)
from pg_constraint
where conrelid = 'public.rqs_uplinks'::regclass
  and contype = 'u';

-- 8. Estado do link de teste
select
  id,
  user_id,
  custom_slug,
  target_url,
  clicks,
  source_instagram,
  source_tiktok,
  source_facebook,
  source_youtube,
  source_direct,
  created_at
from public.rqs_uplinks
where custom_slug = 'flower-newworld';

-- 9. Estado da quota do proprietário do link
select
  p.id,
  p.role,
  p.monthly_clicks,
  p.click_quota
from public.profiles p
join public.rqs_uplinks u
  on u.user_id = p.id
where u.custom_slug = 'flower-newworld';

-- =========================================================
-- DEPENDÊNCIAS / REFERÊNCIAS À RPC ANTIGA
-- BEFORE DROP
-- =========================================================

select
  n.nspname as schema_name,
  p.proname,
  pg_get_function_identity_arguments(p.oid) as args,
  pg_get_functiondef(p.oid) as definition
from pg_proc p
join pg_namespace n
  on n.oid = p.pronamespace
where pg_get_functiondef(p.oid)
  ilike '%increment_uplink_clicks%';