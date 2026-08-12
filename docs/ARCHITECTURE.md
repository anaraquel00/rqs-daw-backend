# RQS DAW Backend Architecture

## Scope

This document describes the currently audited integration architecture around RQS Mastering V2. It is an engineering map, not a deployment credential store. Secrets and secret values must never be documented here.

## Runtime flow

For Mastering V2 the current request path is:

1. Angular frontend calls the backend through `DspService`.
2. `GET /mastering/v2/capabilities` exposes the supported V2 delivery contract.
3. `POST /mastering/v2/process` accepts the Mastering V2 job.
4. Node resolves the input source: local direct upload only when explicitly allowed for local integration, or an S3 key in the normal remote path.
5. Node invokes Python through `src.controllers.mastering_v2_cli`.
6. Python builds the V2 render plan and executes the mastering pipeline.
7. Loudness and True Peak finalization happen in the Python mastering pipeline.
8. Preview returns rendered preview media.
9. Full production output is uploaded to S3 and returned through a time-limited signed download URL.
10. Local integration uses the local-download token path instead of S3 output.

## Preview contract

Preview uses the selected 15-second source range. Full Master uses the full track.

Atmosphere remains compatibility metadata for the currently accepted V2 DSP contract; it must not be documented to the user as an audible Atmosphere-dependent DSP change until such processing is explicitly implemented and validated.

## Important modules

### Node transport/API

- `server.js`
- `src/controllers/mastering-v2.js`
- `scripts/mastering-v2-local-server.js`

### Python mastering

- `src/controllers/mastering_v2.py`
- `src/controllers/mastering_v2_cli.py`
- `src/controllers/core_dsp.py`
- `src/controllers/mastering_loudness.py`
- `src/controllers/mastering_finalizer.py`
- `src/controllers/mastering_metrics.py`
- `src/controllers/mastering_validation.py`
- `src/controllers/mastering_profiles.py`

## Current environment-variable names used by Mastering V2

- `PORT`
- `RQS_PYTHON_BIN`
- `RQS_MASTERING_V2_LOCAL_OUTPUT`
- `RQS_MASTERING_V2_DIRECT_UPLOAD`

Only names are documented. Values belong in deployment secret/environment configuration.

## External systems

The repository contains integrations with AWS S3, FFmpeg, Stripe, and Supabase. Payment/prepaid architecture is currently deferred pending complete production/business information.

## Security boundary

CORS and frontend plan state are not authorization boundaries. Server-side authentication/quota remains a separate open production-security task.

## Local integration

The isolated local integration launcher is:

`./scripts/Start-MasteringV2LocalIntegration.ps1`

The local flow is intended for developer validation and must not be treated as the production authorization model.
