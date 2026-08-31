# Pedalboard 0.9.23 — approved V1 AVX portability artifact

This directory packages the exact native wheel already validated on the V1
linux/amd64 / CPython 3.11 runtime. It changes no RQS DSP, audio parameters,
Setlist engine, Uplink behavior or Stems policy.

- Upstream: https://github.com/spotify/pedalboard
- Version/source commit: 0.9.23 / `87db53bb790ce21bb5da959dc92d462d3858f4fd`
- Portability reference: https://github.com/spotify/pedalboard/pull/466
- Patch: only the CMakeLists.txt/setup.py CPU-flag hunks, default `-mavx`
  instead of `-march=native`; no dependency DSP-source changes.
- Wheel: `pedalboard-0.9.23-cp311-cp311-linux_x86_64.whl`
- SHA256: `d0175688816effb48878c84e0f626e31f735d5b21f338354762546e13b10bca9`
- Validated toolchain: Python 3.11.2, GCC 12.2, CMake 3.25.1, Ninja 1.11.1,
  Debian 12/glibc 2.36. Build Python dependencies are pinned in Dockerfile.rebuild.
- Source submodules are pinned by the upstream commit and listed in
  `upstream-submodules.txt`; original builder package versions are recorded in
  `build-debian-packages.txt`. No floating upstream branch is used.

The application Dockerfile installs this exact hash-verified wheel after dependency
resolution, without accessing a wheel index or changing other Python packages.
The supported artifact is x86_64/CPython 3.11 with AVX; other platforms fail closed.

## Rebuild provenance (not executed by an ordinary application build)

The preserved validated pre-portability runtime image is
`sha256:f22845f79113210763fd56ff6295807e376739a6557cc23d0572e37273042711`,
source tree `ed050f38d4a3d506100ce9e0d352227f675c3ae3`.
Supply that locally preserved image, or a verified registry reference to the same
artifact, as `VALIDATED_RUNTIME_BASE`; no unverified base substitution is permitted.
Example from this directory (use a supported local image tag/reference):

```sh
docker build --build-arg VALIDATED_RUNTIME_BASE=rqs-v1-candidate:20260830-2207 \
  -f Dockerfile.rebuild --target wheel-export --output type=local,dest=wheelhouse .
```

The recipe captures the patch, submodules, package/toolchain versions, compile
commands and wheel hash. All compile commands must use AVX and none may use native,
AVX2, FMA or AVX512 flags. `USE_MARCH_NATIVE` must be absent.
The current shipped wheel is reproducibly identified by its exact SHA; a rebuilt
wheel is not claimed byte-identical until its hash is checked. Do not automatically
replace the approved artifact if rebuilding yields a different hash/toolchain.
Preserve upstream license/notice files included in the wheel (Pedalboard GPLv3).

## Retained acceptance evidence

Native import/operations 10/10, Node 10/10, pytest 227/227 and local application
smoke passed before packaging. Preview and Full final PCM24 outputs passed the
owner-approved cross-platform native portability policy without any DSP edit.
Comparison dtype is float64, normalized PCM24 / 2^23, not float32 arithmetic.

- One normalized PCM24 LSB = 1.1920928955078125e-7.
- Portability-only maximum sample delta <= 4 LSB.
- Portability-only null residual RMS <= 0.5 LSB.
- Preview: maximum 2 LSB; residual -169.32390590251484 dBFS.
- Full: maximum 3 LSB; residual -149.47128988972304 dBFS
  (0.2819196877962334 LSB RMS).
- Structural, loudness/True Peak, finite/clipping and gross spectral/dynamic
  invariants passed. Quantization-noise scale is context, not a proven cause.
- Ordinary same-build/same-runtime deterministic tolerance remains **1e-7**.

This acceptance is specific to the proven native portability build and final
PCM24 output. It is not permission to relax normal tests or change audio behavior.
