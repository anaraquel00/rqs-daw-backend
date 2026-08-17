-- =========================================================
-- RQS PROJECT 1 / FINAL BETA
-- MANUAL PREMIUM APPROVAL — REVIEW / OPERATOR TEMPLATE
-- =========================================================
--
-- PURPOSE
--   Approve exactly one already-authenticated RQS user for manual Premium
--   during WAITLIST_ONLY Final Beta.
--
-- SECURITY MODEL
--   - Email is NOT the authorization key.
--   - The immutable Supabase auth.users.id UUID is the authority.
--   - Expected email is used only as a human/operator cross-check.
--   - The UPDATE targets public.profiles.id only.
--   - This must be executed only from a trusted Supabase SQL/admin session.
--   - Never expose this as a browser/public RPC.
--
-- BEFORE EXECUTION
--   1. User must have logged in at least once so auth.users/profile exist.
--   2. Obtain the exact auth.users.id UUID READ-ONLY.
--   3. Confirm the exact expected login email with the account owner.
--   4. Replace BOTH placeholders below.
--   5. Run on the intended Supabase project only.
--
-- FAIL-CLOSED DEFAULTS
--   The all-zero UUID + .invalid email intentionally match no real user.
-- =========================================================

begin;

do $approval$
declare
  v_user_id uuid := '00000000-0000-0000-0000-000000000000'; -- REPLACE
  v_expected_email text := 'CHANGE_ME@example.invalid';       -- REPLACE
  v_actual_email text;
  v_profile_role text;
  v_updated integer;
begin
  if v_user_id = '00000000-0000-0000-0000-000000000000'::uuid
     or lower(v_expected_email) = 'change_me@example.invalid' then
    raise exception 'PREMIUM_APPROVAL_PLACEHOLDERS_NOT_REPLACED';
  end if;

  select lower(u.email)
    into v_actual_email
  from auth.users as u
  where u.id = v_user_id;

  if not found then
    raise exception 'PREMIUM_APPROVAL_AUTH_USER_NOT_FOUND';
  end if;

  if v_actual_email is null
     or v_actual_email <> lower(trim(v_expected_email)) then
    raise exception 'PREMIUM_APPROVAL_EMAIL_CROSSCHECK_FAILED';
  end if;

  select p.role::text
    into v_profile_role
  from public.profiles as p
  where p.id = v_user_id
  for update;

  if not found then
    raise exception 'PREMIUM_APPROVAL_PROFILE_NOT_FOUND';
  end if;

  if v_profile_role not in ('free', 'premium') then
    raise exception 'PREMIUM_APPROVAL_PROFILE_ROLE_INVALID';
  end if;

  update public.profiles
  set role = 'premium'
  where id = v_user_id;

  get diagnostics v_updated = row_count;
  if v_updated <> 1 then
    raise exception 'PREMIUM_APPROVAL_UPDATE_COUNT_INVALID: %', v_updated;
  end if;

  raise notice 'PREMIUM_APPROVAL_PASS user_id=% role=premium', v_user_id;
end;
$approval$;

-- Operator verification. This deliberately does not print the email.
select id, role, completed_masters
from public.profiles
where id = '00000000-0000-0000-0000-000000000000'::uuid; -- REPLACE with the same UUID

-- IMPORTANT:
-- Review the returned single row before COMMIT.
-- If anything is unexpected, execute ROLLBACK instead.

-- COMMIT IS INTENTIONALLY NOT INCLUDED.
-- Choose exactly one after reviewing evidence:
--   commit;
--   rollback;
