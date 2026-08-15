-- Ephemeral GitHub Actions fixture. This file must never target Supabase.

create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;

create schema auth;

create function auth.uid()
returns uuid
language sql
stable
as $$ select null::uuid $$;

create table public.profiles (
  id uuid primary key,
  role text not null,
  monthly_clicks bigint not null,
  click_quota bigint not null
);

create table public.rqs_uplinks (
  id uuid primary key,
  user_id uuid not null references public.profiles(id),
  custom_slug text not null unique,
  target_url text not null,
  clicks bigint not null default 0,
  source_instagram bigint not null default 0,
  source_tiktok bigint not null default 0,
  source_facebook bigint not null default 0,
  source_youtube bigint not null default 0,
  source_direct bigint not null default 0,
  created_at timestamptz not null default statement_timestamp()
);

alter table public.rqs_uplinks enable row level security;

grant select, update
on table public.profiles, public.rqs_uplinks
to service_role;

create policy "Enable read access for all users"
on public.rqs_uplinks
for select
to public
using (true);

create policy "Permitir inserção de uplinks"
on public.rqs_uplinks
for insert
to authenticated
with check (auth.uid() = user_id);

insert into public.profiles (
  id,
  role,
  monthly_clicks,
  click_quota
) values (
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'premium',
  0,
  1000
);

insert into public.rqs_uplinks (
  id,
  user_id,
  custom_slug,
  target_url
) values (
  '6638dcbb-5454-4b08-a634-4ca5e735b8c9',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'flower-newworld',
  'https://open.spotify.com/track/test'
);

create function public.increment_uplink_clicks(
  link_id uuid,
  source_col text,
  target_user_id uuid
)
returns void
language plpgsql
security definer
as $legacy$
begin
  update public.rqs_uplinks
  set clicks = clicks + 1
  where id = link_id;

  update public.profiles
  set monthly_clicks = monthly_clicks + 1
  where id = target_user_id;
end;
$legacy$;

grant execute
on function public.increment_uplink_clicks(uuid, text, uuid)
to public, anon, authenticated, service_role;
