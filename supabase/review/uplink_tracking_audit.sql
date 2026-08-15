-- =========================================================
-- RQS UPLINK TRACKING — READ-ONLY AUDIT
-- Safe before and after migration. No production mutation.
-- =========================================================

-- 1. Existing RPC signatures, owner and security configuration.
select
  p.oid::regprocedure as signature,
  p.prosecdef,
  p.proowner::regrole as owner,
  p.proconfig
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'increment_uplink_clicks'
  and p.prokind = 'f'
order by p.oid::regprocedure::text;

-- 2. Full RPC definitions.
select
  p.oid::regprocedure as signature,
  pg_get_functiondef(p.oid) as definition
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname = 'increment_uplink_clicks'
  and p.prokind = 'f';

-- 3. Explicit application-role EXECUTE matrix. Missing signatures return null.
select
  role_name,
  signature,
  case
    when to_regprocedure(signature) is null then null
    else has_function_privilege(role_name, signature, 'EXECUTE')
  end as can_execute
from (
  values
    ('anon', 'public.increment_uplink_clicks(uuid,text,uuid)'),
    ('authenticated', 'public.increment_uplink_clicks(uuid,text,uuid)'),
    ('service_role', 'public.increment_uplink_clicks(uuid,text,uuid)'),
    ('anon', 'public.increment_uplink_clicks(uuid,text,text)'),
    ('authenticated', 'public.increment_uplink_clicks(uuid,text,text)'),
    ('service_role', 'public.increment_uplink_clicks(uuid,text,text)')
) as acl(role_name, signature)
order by signature, role_name;

-- PUBLIC and explicit grants as recorded in ACL metadata.
select
  routine_schema,
  routine_name,
  specific_name,
  grantee,
  privilege_type
from information_schema.routine_privileges
where routine_schema = 'public'
  and routine_name = 'increment_uplink_clicks'
order by specific_name, grantee;

-- 4. RLS and policies on both tracking tables.
select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  p.policyname,
  p.permissive,
  p.roles,
  p.cmd,
  p.qual,
  p.with_check
from pg_class as c
join pg_namespace as n on n.oid = c.relnamespace
left join pg_policies as p
  on p.schemaname = n.nspname
 and p.tablename = c.relname
where n.nspname = 'public'
  and c.relname in ('rqs_uplinks', 'rqs_uplink_click_dedup')
order by c.relname, p.policyname;

-- 5. custom_slug uniqueness.
select
  conname,
  pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.rqs_uplinks'::regclass
  and contype = 'u';

-- 6. Product-role inventory. Review every returned value before migration.
select
  p.role,
  count(*) as profiles,
  count(*) filter (where p.monthly_clicks is null) as null_monthly_clicks,
  count(*) filter (where p.click_quota is null) as null_click_quota,
  min(p.click_quota) as min_click_quota,
  max(p.click_quota) as max_click_quota
from public.profiles as p
group by p.role
order by p.role nulls first;

-- 7. Column defaults and nullability. Migration must preserve click_quota.
select
  table_name,
  column_name,
  column_default,
  is_nullable,
  data_type
from information_schema.columns
where table_schema = 'public'
  and (
    (table_name = 'profiles'
      and column_name in ('role', 'monthly_clicks', 'click_quota'))
    or
    (table_name = 'rqs_uplinks'
      and column_name in (
        'clicks',
        'source_instagram',
        'source_tiktok',
        'source_facebook',
        'source_youtube',
        'source_direct'
      ))
  )
order by table_name, ordinal_position;

-- 8. Invalid counter inventory. Expected: all zero.
select
  count(*) filter (where clicks is null) as null_clicks,
  count(*) filter (where source_instagram is null) as null_instagram,
  count(*) filter (where source_tiktok is null) as null_tiktok,
  count(*) filter (where source_facebook is null) as null_facebook,
  count(*) filter (where source_youtube is null) as null_youtube,
  count(*) filter (where source_direct is null) as null_direct
from public.rqs_uplinks;

-- 9. Controlled-link and owner snapshot.
select
  u.id,
  u.user_id,
  u.custom_slug,
  u.target_url,
  u.clicks,
  u.source_instagram,
  u.source_tiktok,
  u.source_facebook,
  u.source_youtube,
  u.source_direct,
  u.created_at,
  p.role,
  p.monthly_clicks,
  p.click_quota
from public.rqs_uplinks as u
join public.profiles as p on p.id = u.user_id
where u.custom_slug = 'flower-newworld';

-- 10. Database functions whose body references the RPC name.
-- prokind filtering prevents pg_get_functiondef errors for aggregates.
select
  n.nspname as schema_name,
  p.oid::regprocedure as signature,
  pg_get_functiondef(p.oid) as definition
from pg_proc as p
join pg_namespace as n on n.oid = p.pronamespace
where p.prokind = 'f'
  and p.proname <> 'increment_uplink_clicks'
  and pg_get_functiondef(p.oid) ilike '%increment_uplink_clicks%'
order by n.nspname, p.oid::regprocedure::text;

-- External consumers cannot be proven from PostgreSQL. Before execution also
-- search every application repository and deployed Edge Function source for:
--   increment_uplink_clicks
--   rqs_uplinks
