# Mastering V2 — Staging S3 / IAM Least-Privilege Contract

Status: **TEMPLATE READY / AWS CREATION NOT AUTHORIZED**

Target architecture:

```text
rqs-daw-backend-staging
-> dedicated staging execution role
-> dedicated staging S3 bucket in sa-east-1
-> Supabase staging uwrqbywapomuloresoek
-> zero permission to production bucket amzn-rqs-bunker-sa
```

## Runtime contract

```text
RQS_PAYMENT_MODE=disabled
RQS_ALLOWED_ORIGINS=<EXACT_PROTECTED_STAGING_FRONTEND_ORIGIN>
RQS_MASTERING_V2_STORAGE_ENV=staging
RQS_MASTERING_V2_BUCKET_NAME=<DEDICATED_STAGING_BUCKET>
RQS_MASTERING_V2_AWS_REGION=sa-east-1
SUPABASE_URL=https://uwrqbywapomuloresoek.supabase.co
SUPABASE_SECRET_KEY=<STAGING_SERVER_SECRET_CONFIGURED_SECURELY>
```

Do not enable deployed staging with:

```text
RQS_MASTERING_V2_LOCAL_OUTPUT=1
RQS_MASTERING_V2_DIRECT_UPLOAD=1
```

Do not provide production Stripe credentials.

## Execution-role object permissions

Minimum observed Mastering V2 requirement:

```text
uploads/*
  s3:PutObject
  s3:GetObject

masters/*
  s3:PutObject
  s3:GetObject
  s3:DeleteObject
```

Explicitly not required/allowed for this contract:

```text
AmazonS3FullAccess
s3:ListBucket
bucket administration
ACL administration
production bucket access
```

Template:

`infra/staging/mastering-v2-execution-role-policy.template.json`

## S3 CORS

The browser PUT/GET boundary uses only the exact protected staging frontend origin.

```text
AllowedOrigins = [exact staging origin]
AllowedMethods = PUT, GET, HEAD
AllowedHeaders = Content-Type
ExposeHeaders = ETag
```

Wildcard origin is forbidden.

Template:

`infra/staging/mastering-v2-cors.template.json`

## Bucket controls required before E2E

```text
Region: sa-east-1
Bucket != amzn-rqs-bunker-sa
Block Public Access: ON
Object Ownership: Bucket owner enforced
ACLs: disabled
Default encryption: ON
Production-bucket permission from staging role: NONE
```

A TLS-only bucket policy may be added during reviewed provisioning. Do not broaden object permissions simply to make legacy Mix/Stems work; Project 1 Mastering staging remains isolated from those legacy production-bucket paths.

## Authorization boundary

These files are templates only.

```text
AWS CREATE BUCKET: NOT AUTHORIZED
AWS CREATE ROLE: NOT AUTHORIZED
AWS ATTACH POLICY: NOT AUTHORIZED
AWS CHANGE S3 CORS: NOT AUTHORIZED
PRODUCTION MUTATION: NONE
```

When AWS staging creation is explicitly authorized, replace placeholders with the final dedicated bucket/origin, validate the rendered policy offline, then apply only to the staging resources.
