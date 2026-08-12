# RQS Cleanup Inventory

This file records cleanup candidates. A candidate is not permission to delete it.

## Large tracked backend files requiring reference verification

- `bg-vol005.jpg`
- `thumbnail.jpg`
- `assets/VIGNETTE_MAIN.1wav`

These files must be checked for runtime/build/documentation references before any removal decision.

## Root-level legacy-looking engines requiring ownership/reference verification

- `audio-splitter.js`
- `glitch-engine.js`
- `monolith-engine.js`

No automatic deletion is authorized.

## Frontend observations from the audit

The following SCSS files are byte-for-byte duplicates:

- `src/app/components/privacy/privacy.scss`
- `src/app/components/terms/terms.scss`

Consolidation is optional and should only be done if it improves maintainability without making component styling less clear.

## Documentation status at audit time

Frontend had:

- `README.md`
- `src/MANUAL_MASTERIZACAO.md`

Backend had:

- `README.md`
- `requirements.txt`
- `tests/BASELINE.md`

The engineering documents in this directory begin the backend architecture/optimization/cleanup baseline.

## Generated/ignored content

The audit found no generated build paths tracked by Git. Large ignored-file counts are expected to include dependencies, caches, build output, and local environment content; ignored files are not cleanup targets solely because they are numerous.

## Final Beta cleanup update

Ana current `main` already removed the confirmed legacy files:

- `audio-splitter.js`
- `glitch-engine.js`
- `monolith-engine.js`
- `thumbnail.jpg`
- `assets/VIGNETTE_MAIN.1wav`

The clean integration branch inherits those deletions from `main`; this
reconciliation does not restore them. No additional runtime file is deleted
by the Mastering V2 integration step.
