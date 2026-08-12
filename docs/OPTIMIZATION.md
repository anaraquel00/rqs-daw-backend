# RQS Optimization Baseline

## Baseline

Audit baseline before optimization:

- Python: 3.12.0
- Node: 22.23.1
- npm: 10.9.8
- FFmpeg: 9.0
- backend tests: 212 passed
- backend full pytest duration: approximately 69 seconds on the audited workstation

## Priority model

Optimization work is split into two classes.

### Safe / no-audio-impact

These changes can be validated with code/unit/integration tests because they do not alter samples produced by the DSP pipeline.

Current first change:

- Mastering V2 production S3 upload: stream the already-rendered WAV from disk instead of loading the complete master with `fs.readFileSync()`.

Reason:

- avoids an extra full-file JavaScript Buffer,
- avoids synchronous file read on the request path,
- does not change Python DSP or the rendered WAV.

### Audio/DSP-sensitive

These are not automatically refactored merely because static analysis reports complexity.

Current candidates include:

- `core_dsp.py::masterize`
- `mastering_finalizer.py::finalize_true_peak`
- `mastering_loudness.py::finalize_loudness`
- full-audio reads inside Python mastering/measurement code

Any change that can alter DSP output remains behind unit/integration plus real-audio validation.

## Other candidates

- frontend waveform currently decodes the full source with Web Audio; this is a future performance candidate if long-track memory use becomes measurable,
- legacy mastering/mix/stem controllers also contain synchronous whole-file reads before S3 operations and should be reviewed separately,
- duplicated E2E bootstrap code can be consolidated later,
- test-duration optimization should not weaken audio quality coverage.

## Non-goal

Code optimization must not change the accepted Mastering V2 sound simply to reduce line count, complexity score, or test duration.
