# RQS Uplink — Abuse Protection

The public `rqs-router` is intentionally unauthenticated because it must accept
normal browser redirects. Public access must not grant direct database writes.

## V3 controls

- only `GET` requests are eligible for tracking;
- `HEAD`, prefetch/prerender and known preview/crawler user agents redirect
  without consuming analytics or quota;
- the Edge Function uses `service_role` only server-side;
- the RPC is executable only by `service_role`;
- raw client addresses and user-agent strings are never stored;
- a salted SHA-256 fingerprint is generated in the Edge Function;
- a database primary key atomically deduplicates the same link/fingerprint in a
  one-minute window across all Edge Function isolates;
- quota checking and counter updates remain in the same database transaction;
- invalid source, fingerprint, role, counters or ownership state fails closed;
- tracking failures never block a valid redirect.

`?src=` is an attribution hint supplied by the link creator. It is useful when
social applications remove the `Referer` header, but it is not cryptographic
proof that the visitor came from that platform.

## Required secret

Configure a high-entropy `UPLINK_TRACKING_SALT` only in the Edge Function
environment. Do not reuse a public Supabase key and never commit the value.

Without the salt or a client address, the router redirects but deliberately
skips tracking.

## Retention

Successful requests create deduplication rows containing only:

- link UUID;
- salted fingerprint hash;
- one-minute window timestamp;
- creation timestamp.

The RPC removes rows older than 48 hours for the active link. A scheduled daily
maintenance job should also delete all rows older than 48 hours so inactive
links do not retain stale hashes.

Example maintenance statement (review before scheduling):

```sql
delete from public.rqs_uplink_click_dedup
where created_at < statement_timestamp() - interval '48 hours';
```

## Residual risk

No public click counter can perfectly distinguish a person from a sufficiently
realistic automated browser. The one-minute deduplication window limits simple
repeats but does not prevent distributed abuse using many addresses or user
agents. Monitor `trackingError`, `trackingDeduplicated` and request volume, then
add infrastructure-level rate limiting if abuse is observed.
