# Mastering V2 Project 1 — Frontend Security Follow-up

Status: PREPARED / DO NOT APPLY TO STALE FRONTEND MAIN

This follow-up should start only from the actual frontend production baseline after Ana's final decision on frontend PR #2.

Required changes:

1. Keep `/mastering/v2/capabilities` public/read-only.
2. For `/mastering/v2/presigned-url` and `/mastering/v2/process`, send the current Supabase user access token as:
   `Authorization: Bearer <user access token>`.
3. Use `/mastering/v2/presigned-url`; do not use the legacy `/mastering/presigned-url` for Mastering V2.
4. Do not log the access token.
5. Treat backend quota as authoritative.
6. Remove the client-side `completed_masters + 1` mutation after Full Master success.
7. Refresh the authenticated profile after a confirmed Full Master so the UI reflects server state.
8. Preserve Ana-approved behavior:
   - OAuth redirect to `/app`
   - Free 3/3 hides Full Master
   - Final Beta / RQS PRO waitlist replaces it
   - Preview 15 seconds and selected range
   - A/B
   - SSR guards
   - PL/PT/EN
9. Add tests for:
   - Authorization header present on secure V2 calls
   - no Authorization header required for capabilities
   - no client-side quota increment
   - profile refresh after successful Full Master
   - 401/403/429 backend responses shown safely to user

Do not implement this file against old frontend `main` if PR #2 has not been reconciled. Verify actual `main` first.
