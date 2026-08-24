-- CI fixture for observed production auth -> profiles baseline.

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
  role text null default 'free',
  completed_masters integer null default 0
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
as $function$
begin
  insert into public.profiles (id, email, role, completed_masters)
  values (new.id, new.email, 'free', 0);
  return new;
end;
$function$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

grant execute on function public.handle_new_user() to anon, authenticated, service_role;
