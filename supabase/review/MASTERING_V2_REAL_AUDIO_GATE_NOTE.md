# Mastering V2 — local real-audio gate note

Status: VALIDATOR SELECTION FIXED / real-audio rerun required
Date: 2026-08-16

## Observed run

The first local real-audio integration run correctly refreshed the current inventory under:

`D:\RQS-Dev\real_audio_ab\input\Testes RQS DAW`

The current folder did not contain an unambiguous `HUSARIA` or `Kwiat` premaster, so the validator stopped before candidate extraction/render with:

`Could not select one unambiguous HUSARIA/Kwiat premaster.`

This is a validator-selection issue, not a DSP/backend failure. No S3, Supabase, production request, or canonical Git mutation occurred.

## Fix

The validator now follows the accepted project real-audio order:

1. PRIMARY — `4-Lockdown Protocol.wav`, validated window 145-175 s; Preview starts at 145 s.
2. BACKUP — `7-Cybernetic Grid*.wav`, validated window 285-315 s; Preview starts at 285 s.
3. Historical HUSARIA fallback — Preview starts at 290 s.
4. Historical Kwiat fallback — Preview starts at 270 s.

`-InputFile` remains supported, and `-PreviewStart` can now be supplied explicitly. For a recognized explicit input, the validator infers the corresponding validated Preview window start. For an unknown explicit WAV it fails closed and requires `-PreviewStart`.

## Gate

Real-audio integration remains OPEN until the rerun completes and produces:

- canonical DSP hash parity PASS;
- HTTP Preview render PASS;
- canonical Preview render PASS;
- exact 15-second Preview PASS;
- HTTP/canonical Preview sample parity PASS;
- HTTP Full Master render/download PASS;
- canonical Full Master render PASS;
- HTTP/canonical Full Master sample parity PASS;
- full duration preserved PASS;
- evidence ZIP + SHA256.

AWS/S3 remains a separate HOLD because no local AWS identity/credentials are configured.
