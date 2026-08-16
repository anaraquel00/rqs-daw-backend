-- Ephemeral GitHub Actions fixture for Mastering V2 security SQL.
-- This file mirrors the observed production profiles security baseline closely
-- enough to exercise the hardening migration. NEVER run it against Supabase.

create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;

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
  email text null,
  role text null default 'free',
  completed_masters integer null default 0,
  monthly_clicks integer null default 0,
  click_quota integer null default 1000
);

alter table public.profiles enable row level security;

-- Mirror the observed legacy Supabase table grants: browser roles have broad
-- table privileges, while RLS determines row access. This is intentionally
-- insecure for UPDATE and exists only in this ephemeral CI fixture so the
-- migration proves it retires that authority.
grant all privileges on table public.profiles to anon, authenticated, service_role;

create policy "Usuários autenticados leem o próprio perfil"
on public.profiles
for select
to authenticated
using ((select auth.uid()) = id);

create policy "Permitir que usuários atualizem seus próprios perfis"
on public.profiles
for update
to authenticated
using (auth.uid() = id)
with check (auth.uid() = id);

insert into public.profiles (id, email, role, completed_masters, monthly_clicks, click_quota)
values
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1'::uuid, 'free-ci@example.invalid', 'free', 2, 0, 1000),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2'::uuid, 'premium-ci@example.invalid', 'premium', 999, 0, 1000);
