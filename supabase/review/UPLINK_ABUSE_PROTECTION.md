# RQS Uplink — Abuse Protection

## Current V2 protection

The public `rqs-router` is intentionally unauthenticated.

The database enforces:

- one validated tracking RPC;
- service_role-only EXECUTE;
- Free monthly quota;
- atomic quota locking;
- source allowlist.

## Remaining abuse risk

A third party can repeatedly invoke a public Uplink URL and artificially consume
the link owner's Free quota.

Application-local in-memory rate limiting is not sufficient because Edge
Functions can run across multiple isolates/instances.

## Proposed next control

Add a distributed rate limiter / deduplication layer before invoking the
tracking RPC.

Candidate policy:

- key: hash(link_id + client fingerprint)
- short window: 30–60 seconds
- repeated request inside the window:
  - redirect normally;
  - do not increment analytics/quota.

No raw IP should be persisted.

This control must be reviewed separately before production deployment.
