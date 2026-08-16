-- Ephemeral GitHub Actions fixture for Mastering V2 security SQL.
-- This file must never target Supabase or production.

create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;

create table public.profiles (
  id uuid primary key,
  role text not null,
  completed_masters bigint not null default 0
);

grant select, update
on table public.profiles
to service_role;

insert into public.profiles (id, role, completed_masters)
values
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1'::uuid, 'free', 2),
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2'::uuid, 'premium', 999);
