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
--   - Execute only from a trusted Supabase SQL/admin session.
--   - Never expose this as a browser/public RPC.
--
-- OPERATOR WORKFLOW
--   1. User logs in at least once so auth.users/profile exist.
--   2. Obtain auth.users.id READ-ONLY.
--   3. Confirm expected login email with the account owner.
--   4. Replace the UUID and email once in premium_approval_input below.
--   5. First run MUST keep the final ROLLBACK. Verify exactly one row.
--   6. Only after successful review change final ROLLBACK to COMMIT and rerun.
--
-- FAIL-CLOSED DEFAULTS
--   The all-zero UUID + .invalid email intentionally match no real user.
-- =========================================================

begin;

create temporary table premium_approval_input (
  user_id uuid primary key,
  expected_email text not null
) on commit drop;

insert into premium_approval_input (user_id, expected_email)
values (
  '00000000-0000-0000-0000-000000000000', -- REPLACE ONCE
  'CHANGE_ME@example.invalid'                -- REPLACE ONCE
);

do $approval$
declare
  v_user_id uuid;
  v_expected_email text;
  v_actual_email text;
  v_profile_role text;
  v_updated integer;
begin
  select user_id, expected_email
    into v_user_id, v_expected_email
  from premium_approval_input;

  if v_user_id = '00000000-0000-0000-0000-000000000000'::uuid
     or lower(trim(v_expected_email)) = 'change_me@example.invalid' then
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

-- Verification deliberately does not expose the email.
select p.id, p.role, p.completed_masters
from public.profiles as p
join premium_approval_input as i on i.user_id = p.id;

-- =========================================================
-- SAFE DEFAULT: DRY RUN ONLY
-- Keep ROLLBACK for the first reviewed execution.
-- After a PASS and human verification of exactly one intended UUID,
-- change ONLY this final word to COMMIT and rerun the identical script.
-- =========================================================
rollback;
