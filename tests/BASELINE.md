# RQS mastering baseline tests

These tests document the state of the legacy mastering engine before any DSP
changes.

## Meaning of results

- `PASSED` — existing behavior already meets the minimal requirement.
- `XFAIL` — a confirmed known defect was reproduced as expected.
- `XPASS` — the engine unexpectedly satisfies a previously failing requirement;
  investigate and remove the corresponding `xfail` marker only after validation.
- `FAILED` — a smoke test or test harness failed and requires diagnosis.

The baseline suite must not modify `src/controllers/core_dsp.py`.
Audio fixtures are generated inside pytest temporary directories and are not
stored in Git.
