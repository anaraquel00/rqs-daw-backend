-- Ephemeral CI fixture mirroring the observed rqs-daw-staging profiles baseline.
-- NEVER run against Supabase.

create schema auth;

create function auth.uid()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

grant usage on schema auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;

create table public.profiles (
  id uuid primary key,
  role text not null check (role in ('free','premium')),
  monthly_clicks bigint not null default 0,
  click_quota bigint not null default 1000
);

-- Observed isolated Uplink staging baseline: RLS disabled, no policies, reduced
-- grants, one synthetic premium profile and no auth.users linkage.
grant references, trigger, truncate
on table public.profiles
to anon, authenticated;

grant select, update, references, trigger, truncate
on table public.profiles
to service_role;

insert into public.profiles (id, role, monthly_clicks, click_quota)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid, 'premium', 0, 1000);
