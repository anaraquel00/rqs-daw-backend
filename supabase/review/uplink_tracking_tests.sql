-- =========================================================
-- TEST A — ACL OLD SIGNATURE
-- BEFORE MIGRATION
-- =========================================================

select
  has_function_privilege(
    'anon',
    'public.increment_uplink_clicks(uuid,text,uuid)',
    'EXECUTE'
  ) as old_anon,

  has_function_privilege(
    'authenticated',
    'public.increment_uplink_clicks(uuid,text,uuid)',
    'EXECUTE'
  ) as old_authenticated,

  has_function_privilege(
    'service_role',
    'public.increment_uplink_clicks(uuid,text,uuid)',
    'EXECUTE'
  ) as old_service_role;


-- =========================================================
-- TEST B — ACL NEW SIGNATURE
-- POST MIGRATION
--
-- expected:
-- anon=false
-- authenticated=false
-- service_role=true
-- =========================================================

select
  has_function_privilege(
    'anon',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as new_anon,

  has_function_privilege(
    'authenticated',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as new_authenticated,

  has_function_privilege(
    'service_role',
    'public.increment_uplink_clicks(uuid,text)',
    'EXECUTE'
  ) as new_service_role;

  -- =========================================================
-- TEST C — NULL SOURCE
-- EXPECTED: INVALID_SOURCE
-- ZERO COUNTERS CHANGED
-- =========================================================

-- select public.increment_uplink_clicks(
--   '<TEST_LINK_ID>'::uuid,
--   null
-- );


-- =========================================================
-- TEST D — INVALID SOURCE
-- EXPECTED: INVALID_SOURCE
-- =========================================================

-- select public.increment_uplink_clicks(
--   '<TEST_LINK_ID>'::uuid,
--   'source_fake'
-- );


-- =========================================================
-- TEST E — UNKNOWN LINK
-- EXPECTED: UPLINK_NOT_FOUND
-- =========================================================

-- select public.increment_uplink_clicks(
--   '00000000-0000-0000-0000-000000000000'::uuid,
--   'source_direct'
-- );

-- =========================================================
-- TEST F — FREE QUOTA EXCEEDED
--
-- BUSINESS RULE:
-- Free = 700 tracked clicks/month
-- Premium = unlimited tracking
-- Redirect = unlimited for both plans
--
-- PRE:
-- role = 'free'
-- monthly_clicks = 700
-- click_quota = 700
--
-- EXPECTED:
-- CLICK_QUOTA_EXCEEDED
-- clicks unchanged
-- source_* unchanged
-- monthly_clicks unchanged
-- redirect still succeeds
-- =========================================================

-- =========================================================
-- TEST G — PREMIUM BUSINESS RULE
--
-- BUSINESS RULE:
-- Premium tracking = unlimited
--
-- PRE:
-- role = 'premium'
-- monthly_clicks >= click_quota
--
-- EXPECTED:
-- RPC succeeds
-- clicks +1
-- selected source +1
-- monthly_clicks +1
-- redirect succeeds
-- =========================================================

-- =========================================================
-- TEST H — CONCURRENCY
--
-- PRE:
-- role='free'
-- click_quota - monthly_clicks = 1
--
-- Run several service_role RPC calls concurrently.
--
-- EXPECTED:
-- exactly 1 success
-- remaining calls => CLICK_QUOTA_EXCEEDED
--
-- FINAL:
-- clicks increased exactly by 1
-- selected source increased exactly by 1
-- monthly_clicks increased exactly by 1
-- =========================================================

-- =========================================================
-- TEST I — REDIRECT AFTER TRACKING ERROR
--
-- Router test, not pure SQL.
--
-- Force quota exceeded / tracking error.
--
-- EXPECTED:
-- structured trackingError in logs
-- HTTP redirect still reaches target_url
-- no tracking counters changed
-- =========================================================

-- =========================================================
-- TEST J — POST ROLLBACK
--
-- EXPECTED:
-- only old (uuid,text,uuid) contract restored
-- original ACL restored
-- public SELECT policy restored
-- router source restored from index.before.ts
-- =========================================================