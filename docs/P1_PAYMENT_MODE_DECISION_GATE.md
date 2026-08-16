# Project 1 — Payment Mode Decision Gate

Status: **DECISION REQUIRED / SAFE DEFAULT RECOMMENDATION: WAITLIST_ONLY**

Project 1 must explicitly choose one of:

```text
P1_PAYMENT_MODE=WAITLIST_ONLY
P1_PAYMENT_MODE=LIVE_PAYMENT
```

This is a product/release decision. The repository must not infer `LIVE_PAYMENT` from the mere presence of Stripe credentials.

## Current security classification

The existing payment path is not sufficient evidence for production entitlement safety.

Confirmed concerns from the current implementation/review:

- entitlement upgrade is keyed by Stripe customer e-mail rather than immutable RQS user ID;
- production profile e-mail is not proven to be a unique immutable entitlement key;
- no auth-update synchronization contract keeps profile e-mail authoritative;
- webhook handling does not prove the expected offer/product/price contract;
- webhook handling does not prove the intended Stripe mode/livemode/payment-status contract before granting Premium;
- a successful upstream profile PATCH HTTP response does not by itself prove exactly one intended profile was promoted;
- historical exposure of the webhook signing secret requires rotation before relying on that trust boundary;
- the active frontend Project 1 Pro path is currently a waitlist path, not a validated live checkout lifecycle.

Therefore `LIVE_PAYMENT` remains **HOLD** until a separate payment hardening stage is implemented and validated.

## Recommended Project 1 decision

```text
P1_PAYMENT_MODE=WAITLIST_ONLY
```

Rationale:

- preserves the existing Final Beta / RQS PRO waitlist UX;
- keeps Mastering staging independent from production Stripe secrets;
- removes payment entitlement from the critical Mastering V2 cutover path;
- avoids treating an incomplete e-mail-bound webhook flow as a production authorization boundary;
- permits Stripe/payment hardening to be completed as a separate controlled stage.

The recommendation is not an automatic production mutation. Final product approval remains explicit.

## WAITLIST_ONLY contract

When approved:

- no visible live checkout/upgrade action in Project 1;
- Mastering-only staging uses `RQS_PAYMENT_MODE=disabled`;
- production cutover must not accidentally enable a new payment CTA;
- existing waitlist behavior remains available at Free `3/3`;
- credential rotation still proceeds because exposed Stripe credentials remain a security issue even if live payment is disabled;
- payment webhook behavior is not used as a release-success criterion for Mastering V2.

## LIVE_PAYMENT additional mandatory gates

Do not approve `LIVE_PAYMENT` until all are closed:

1. immutable RQS user/account identifier bound to Stripe customer/session metadata;
2. exact intended product/price/offer validation;
3. explicit Stripe mode/livemode validation;
4. successful-payment state validation before entitlement;
5. idempotent event processing and replay handling;
6. exact-one-user entitlement update semantics;
7. webhook event identity/history/audit trail;
8. e-mail is not the sole privilege key;
9. subscription/refund/cancellation entitlement behavior defined where applicable;
10. rotated Stripe API and webhook signing credentials;
11. negative tests for forged/wrong-product/wrong-user/replayed events;
12. isolated Stripe test-mode E2E PASS;
13. explicit production payment authorization.

## Release classification

Until the user records the final decision:

```text
P1_PAYMENT_MODE: OPEN
LIVE_PAYMENT: HOLD
MASTERING_STAGING_PAYMENT_MODE: DISABLED
```

The Mastering Phase A/Phase B staging work may continue because it is intentionally payment-disabled.
