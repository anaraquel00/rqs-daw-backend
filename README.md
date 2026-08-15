# RQS DAW Backend

Backend and audio-processing core for **RQS Studio**, an actively developed web-based music technology platform in the RaQuel Synths ecosystem.

This repository combines a **Node.js / Express 5 HTTP API** with **Python DSP and source-separation modules**, plus AWS S3 integration, Stripe webhook handling, Supabase integration, FFmpeg-based rendering and an expanding automated test suite.

> **Project status:** actively developed independent product. The repository contains production-facing code as well as modules and review packages that are still being validated before wider SaaS/B2B use. This README intentionally distinguishes implemented functionality from items that still require hardening or operational validation.

## What is implemented

### HTTP/API layer

The application entry point is `server.js` and exposes modular Express routes for:

- `GET /health` — application health response
- `/mastering` — upload, S3 transfer and DSP orchestration
- `/mix` — multi-track setlist generation with FFmpeg
- `/video` — audio-reactive visual rendering
- `/stems` — Demucs-based six-stem separation
- `/payment` — Stripe webhook processing

CORS is currently restricted to the local Angular development origin, the Vercel frontend and `https://studio.raquelsynths.com`. The Express JSON parser preserves `req.rawBody` for Stripe webhook signature verification.

### Audio mastering path

`src/controllers/mastering.js` provides two input paths:

1. direct multipart upload to the container's `/tmp` storage;
2. S3-backed processing through presigned upload URLs.

The S3 flow currently accepts `.wav` and `.mp3` filenames when creating presigned upload URLs. Full mastering results are written back to S3 and returned through time-limited presigned download URLs. Preview mode returns a rendered WAV directly.

The HTTP controller launches the Python DSP entry point with `child_process.spawn`, captures stdout/stderr and removes temporary input/output files after processing.

### DSP engine

The repository currently contains two related DSP implementations:

- `src/controllers/core_dsp.py` — the active adaptive mastering entry point used by `mastering.js`;
- `src/controllers/mastering_engine/` — a more modular mastering architecture with separate metering, DSP and pipeline components.

The active `core_dsp.py` includes:

- mono/stereo input handling;
- LUFS measurement with `pyloudnorm`;
- input pre-gain/headroom logic;
- adaptive crest-factor analysis;
- Mid/Side processing;
- transient restoration;
- high-frequency side saturation with 4x oversampling;
- multiband splitting;
- high-frequency cleanup;
- atmosphere/profile-dependent processing;
- configurable target LUFS and limiter-ceiling overrides;
- 15-second center-preview loading;
- guarded temporary-output publication and output validation.

### Mastering V2 model

`mastering_profiles.py` and `mastering_v2.py` introduce a delivery-oriented mastering contract instead of treating creative character and delivery loudness as the same setting.

Supported delivery destinations currently include:

- streaming;
- club;
- festival.

Streaming platform profiles currently include:

- Spotify;
- Apple Music;
- YouTube;
- SoundCloud;
- generic streaming.

Creative atmospheres are modeled separately:

- `clear_sky` — Transparent & Balanced
- `thunder` — Punch & Low-End Impact
- `sunroof` — Bright & Open
- `aurora` — Warm & Cinematic

The V2 request model validates allowed LUFS ranges and derives a true-peak ceiling from the delivery target. At 0% character amount, non-preview renders can take a delivery-only loudness path instead of applying the full creative atmosphere processing.

### Modular mastering engine

`src/controllers/mastering_engine/` contains reusable components for a more structured DSP pipeline:

```text
mastering_engine/
├── analysis/
│   └── metering.py
├── dsp/
│   ├── crossover.py
│   ├── limiter.py
│   ├── stereo.py
│   └── transients.py
└── pipeline/
    └── mastering.py
```

Implemented modules include:

- `AudioMeter` — LUFS/LRA, true-peak approximation, sample peak, crest factor, PLR, DC offset and stereo correlation;
- `LinkwitzRileyCrossover` — three-band zero-phase crossover implementation;
- `MidSideStereoProcessor` — Mid/Side encoding, low-frequency side reduction, optional side saturation, width control and correlation safeguard;
- `AdaptiveTransientShaper` — transient enhancement with crest-factor-dependent protection;
- `TruePeakLimiter` — 4x oversampled lookahead-style limiting processed in chunks;
- `MasteringPipeline` — orchestration, input/output metering, configurable profiles and JSON validation/report generation.

These modules exist in the repository and have dedicated tests, but the legacy/active HTTP mastering route and the modular V2 pipeline are still in the process of convergence. Do not assume every modular component is already used by every production request path.

### Input/output safety

`mastering_validation.py` provides explicit mastering-contract checks:

- input file must exist;
- input and output paths must differ;
- an existing output is not silently overwritten;
- supported channel layouts are mono and stereo;
- supported sample-rate range is currently 32 kHz to 192 kHz;
- minimum duration is 0.5 seconds;
- decoded audio must contain finite samples;
- effectively silent inputs are rejected;
- rendered outputs are reopened and checked for sample-rate/channel consistency and finite samples;
- temporary output files are published without overwriting an existing destination.

## Stem separation

`stem-splitter.js` delegates source separation to `core_demucs.py`.

The Python worker invokes Demucs with the `htdemucs_6s` model, packages generated WAV stems into a ZIP archive and reports the result back to Node through stdout.

Two API paths exist:

- S3-backed separation (`/stems/split-s3`);
- direct multipart upload (`/stems/split`).

Temporary files are created under `/tmp` and cleaned after delivery or failure handling.

## Setlist / mix generation

`mix-generator.js` uses FFmpeg through `fluent-ffmpeg`.

The S3-backed mix route can:

- download multiple source tracks from S3;
- chain configurable `acrossfade` transitions;
- map application-level fade choices to FFmpeg curves;
- overlay a vignette/ID track;
- apply a time-based volume-ducking envelope;
- optionally run FFmpeg loudness normalization;
- render a WAV result;
- upload the result to S3;
- return a presigned download URL.

A legacy direct-upload mix route also remains for local/compatibility use.

## Video rendering

`video-engine.js` contains an FFmpeg-based visual rendering route that combines audio with preset-specific backgrounds and a generated frequency visualization.

The current implementation includes Blue Team and Red Team visual presets and is still tightly coupled to repository assets/local paths. It should be treated as a project feature rather than a generalized media-rendering service.

## Payments and account upgrade flow

`payment.js` handles Stripe webhooks and verifies webhook signatures using the raw request body preserved by Express.

For `checkout.session.completed`, the current implementation:

1. reads the normalized customer e-mail from Stripe;
2. uses a Supabase admin client;
3. updates the matching profile role to `premium`.

Environment variables currently referenced by this module:

```text
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
SUPABASE_URL
SUPABASE_SECRET_KEY
```

### Important SaaS limitation

The current payment model is **user/profile-oriented**, not yet a complete B2B subscription model. The repository does not currently provide enough evidence to claim organization-level subscriptions, multi-tenant billing, seat management, invoices, entitlement history or full idempotent subscription lifecycle handling.

Those are planned hardening areas for the B2B SaaS direction rather than completed capabilities.

## AWS / container architecture

The repository Dockerfile is based on `node:22-bookworm` and installs:

- Node.js dependencies;
- Python 3 and virtual environment support;
- `libsndfile`;
- FFmpeg;
- Python DSP dependencies;
- PyTorch / Torchaudio CPU packages;
- Demucs;
- the AWS Lambda Adapter.

The image also preloads the `htdemucs_6s` model into `TORCH_HOME` during build.

The codebase uses AWS S3 in `sa-east-1` and relies on `/tmp` for writable ephemeral processing storage.

### Dockerfile audit note

The current Dockerfile performs more than one Node dependency installation (`npm install`) and installs several packages explicitly after the initial dependency install. This works as an evolving build strategy but should be simplified before the image is treated as a mature reproducible SaaS build. Prefer a single lockfile-driven installation path (`npm ci`) once dependencies and image structure are stabilized.

## Supabase / Uplink security review package

`supabase/review/` contains an **explicit review package**, not an automatically deployed migration.

The current main branch contains:

- a router review directory;
- an audit SQL script;
- migration SQL;
- rollback SQL;
- SQL tests.

A separate open review PR extends this area with additional security hardening, CI validation, RLS/RPC changes, rolling deduplication and deployment/rollback documentation. Because that PR has not been merged, its proposed behavior is intentionally **not described here as current main-branch behavior**.

## Testing

The repository contains two Python test locations:

### `src/tests/`

Tests for the modular mastering engine, including:

- crossover;
- limiter;
- pipeline;
- stereo processing;
- transient processing.

`src/tests/test_metering.py` currently exists but is empty.

### `tests/`

A broader regression/safety suite including tests for areas such as:

- mastering baseline behavior;
- input safety;
- mastering profiles;
- loudness behavior;
- metrics;
- finalization;
- atmosphere DSP guards;
- creative DSP quality;
- high-frequency cleanup;
- Mastering V2 routing and user-loudness behavior.

The repository also contains:

- `pytest.ini`;
- `Run-RqsBaselineTests.ps1`;
- `tests/BASELINE.md`;
- `.cursor/rules/mastering-safety.mdc` with DSP safety/development rules.

### Node test-script limitation

The current root `package.json` still defines:

```json
"test": "echo \"Error: no test specified\" && exit 1"
```

So the root Node package does **not** currently expose a functional automated JavaScript test command. Python tests exist independently through pytest.

## Main technology stack

### Runtime / API

- Node.js 22
- Express 5
- CommonJS
- CORS
- Multer

### Audio / DSP

- Python 3
- NumPy
- SciPy
- SoundFile
- pyloudnorm
- Pedalboard
- FFmpeg
- Demucs
- PyTorch / Torchaudio

### Cloud / integrations

- AWS S3
- AWS Lambda Adapter / container-based deployment path
- Stripe
- Supabase

### Testing / validation

- pytest
- Pydantic
- repository baseline tests
- DSP regression and safety tests

## Repository structure

```text
rqs-daw-backend/
├── .cursor/rules/
│   └── mastering-safety.mdc
├── Dockerfile
├── README.md
├── Run-RqsBaselineTests.ps1
├── package.json
├── pytest.ini
├── requirements.txt
├── server.js
├── src/
│   ├── controllers/
│   │   ├── core_demucs.py
│   │   ├── core_dsp.py
│   │   ├── lufs_radar.py
│   │   ├── mastering.js
│   │   ├── mastering_atmospheres.py
│   │   ├── mastering_engine/
│   │   ├── mastering_finalizer.py
│   │   ├── mastering_loudness.py
│   │   ├── mastering_metrics.py
│   │   ├── mastering_profiles.py
│   │   ├── mastering_v2.py
│   │   ├── mastering_validation.py
│   │   ├── mix-generator.js
│   │   ├── payment.js
│   │   ├── stem-splitter.js
│   │   └── video-engine.js
│   └── tests/
├── supabase/
│   └── review/
└── tests/
```

## Local development

### Node dependencies

```bash
npm install
```

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the API

```bash
node server.js
```

Default port:

```text
8080
```

Health check:

```text
GET /health
```

### Run Python tests

```bash
pytest
```

The exact test outcome depends on the local environment and optional heavy audio/ML dependencies. This README does not claim a specific pass count unless it has been verified for the commit being documented.

## Current engineering limitations and B2B SaaS roadmap

The repository already contains meaningful product, audio-processing and cloud-integration work, but several areas remain necessary before describing the system as a mature B2B SaaS platform.

### High priority

- formal organization/tenant data model;
- tenant isolation tests;
- organization-level RBAC;
- server-side subscription/entitlement model beyond a single `premium` profile role;
- Stripe lifecycle handling beyond `checkout.session.completed`;
- webhook idempotency and subscription state reconciliation;
- centralized structured logging and request/job correlation IDs;
- explicit job state model for long-running mastering/stem work;
- queue/worker strategy for processing that should not remain tied to one long HTTP request;
- least-privilege AWS IAM policies;
- retention/cleanup policy for uploaded and generated media;
- reproducible container dependency installation;
- systematic API authentication/authorization review across all routes.

### Strong next-stage improvements

- CloudWatch/Sentry/OpenTelemetry-style observability;
- per-tenant quotas and usage accounting;
- retry/idempotency strategy for S3, DSP jobs and billing events;
- organization audit logs;
- backup/restore validation;
- security scanning and dependency gates in CI;
- load/concurrency testing for audio-processing workloads;
- explicit staging environment and documented release gates.

## Evidence policy for this README

This documentation was rewritten from an audit of the repository's current `main` branch. It deliberately avoids claiming:

- benchmark numbers that are only written in comments/older documentation but are not independently reproduced here;
- enterprise-grade scalability;
- complete B2B multi-tenancy;
- complete observability;
- complete production security;
- functionality that exists only in an unmerged pull request.

The goal is to keep the README aligned with what the source tree currently demonstrates while making limitations visible enough for technical review and future SaaS hardening.

## Related frontend

RQS Studio frontend:

`anaraquel00/rqs-daw-frontend`

Public studio:

`https://studio.raquelsynths.com/app`

Creator / engineering portfolio:

`https://raquelsynths.com/creator`
