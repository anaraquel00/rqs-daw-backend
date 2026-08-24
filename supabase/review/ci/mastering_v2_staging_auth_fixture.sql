-- CI fixture for observed isolated staging Auth baseline.

create role anon nologin;
create role authenticated nologin;
create role service_role nologin;

create schema auth;
create schema if not exists public;

create table auth.users (
  id uuid primary key,
  email text null
);

create table public.profiles (
  id uuid primary key,
  email text null,
  role text not null default 'free' check (role in ('free','premium')),
  completed_masters integer not null default 0
);
