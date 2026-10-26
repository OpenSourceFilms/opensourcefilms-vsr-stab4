# STAB4: source-flow temporal stabilisation for video upscaling

**Experimental OSF post-processing of frames made using other people's video restoration tools, especially SeedVR2. This is not a new AI model or a SeedVR2 implementation.**

**Credit first:** [SeedVR / SeedVR2 research by ByteDance Seed](https://github.com/ByteDance-Seed/SeedVR), [ComfyUI-SeedVR2 by NumZ, Adrien Toupet and contributors](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler), and [OpenCV](https://opencv.org/) / [NumPy](https://numpy.org/) provide the upstream restoration, integration and computational foundations. OSF's contribution is the particular experimental temporal post-processing and reproducible wrapper. Read [ATTRIBUTION.md](ATTRIBUTION.md) for authors, citations and exact ownership boundaries.

**Frozen research implementation with passing synthetic native-render tests.**

A standalone Python/OpenCV implementation of Open Source Films' frozen
radius-four temporal-detail stabilisation method for image sequences.
It combines an original low-resolution photographic source with a separately
generated higher-resolution frame sequence, estimating optical flow and
locally weighted detail across nearby frames.

This is not a generative upscaler or a compositing system. It deliberately
keeps the original source, enhanced candidates and newly rendered output in
separate directories.

## Reproduce using only synthetic data

Tested on Python 3.11 using pinned NumPy and OpenCV with DIS optical flow support:

```bash
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -p 'test_vsr_stab4_engine_v1.py' -v
python examples/make_synthetic.py /tmp/stab4-example-unique
python vsr_stab4_engine_v1.py probe /tmp/stab4-example-unique/request.json
python vsr_stab4_engine_v1.py run /tmp/stab4-example-unique/request.json --workers 1
python vsr_stab4_engine_v1.py verify /tmp/stab4-example-unique/request.json
```

Choose a new directory that does not already exist; the generator and engine
are create-only by design. `run` records input hashes in
`rendered/run_index.json`; `verify` checks exact input/output continuity.
Do not point the output directory at source footage. For a partial run or
restart, use the engine's `--only-frames` / `--resume` behavior and the
existing manifest. See the source and tests for the exact allowed schema.

The synthetic generator uses 8-bit RGB PNGs at 16×16 for source frames and
16-bit RGB PNGs at 32×32 for enhanced frames. It is **not** sample LifeR
footage, a model checkpoint, or a claim of film-quality stabilization.

## Read-only PNG source sequence fingerprints

An optional [standalone Python inventory](vsr_sequence_inventory.py)
provides bytewise SHA-256 identities for ordered PNG frame sequences,
using the original versioned `OSF-VSR-SOURCE-SEQUENCE-v1` fingerprint
contract. It can help verify source lineage before or after STAB4 without
running neural models or changing the render method. It is **not a PNG
decoder, full CRC audit, colour qualification or creative acceptance tool**.

See the [sequence-inventory guide](docs/sequence-inventory.md). Its
**21 independent synthetic unit tests** run with Python's standard library,
without ComfyUI, inference, model weights or film footage.

The inventory now also rejects malformed IHDR payload lengths and RGB files
incorrectly declared with straight or premultiplied alpha. It still does not
validate PNG CRCs, decode pixels or establish alpha premultiplication quality.
Valid source-sequence fingerprint serialization is unchanged.

The engine's input and output header checks now require a PNG IHDR chunk
payload length of exactly 13 bytes. This rejects a malformed file before
recording source identity or accepting a rendered output as verified. The
check does not decode PNG pixels or check CRCs and does not alter the frozen
STAB4 stabilisation calculations.

Partial resume now rejects symlinked or non-regular previously recorded
output frames, even when the symlink target's bytes match the journalled
hash. Recovered, unjournalled destination frames must also be regular,
non-symlink files before their hashes are compared. The
`run_index.json` integrity journal is also required to be a regular,
non-symlinked file before resume or verification reads it; this prevents a
path redirect into an external journal. These checks avoid following
potentially redirected paths and do not change the numerical
stabilisation method.

## Verification and limitations

- 19/19 synthetic engine tests passed on OSF's native Python 3.11,
  OpenCV/NumPy runtime on 25 October 2026, including real native rendering.
- This test suite checks manifests, integrity, unexpected files, resume,
  resource admission and a small actual OpenCV render.
- The frozen algorithm is intentionally not changed here, including its
  motion-trust behavior. Scene cuts and fast motion may smear or trail.
- The engine's own docstring distinguishes mathematical implementation from
  complete golden-frame or full-shot creative acceptance. The latter is
  **not** claimed by this candidate.
- 16-bit PNGs created by integer expansion of 8-bit data do not contain extra
  source information merely because they use 16-bit storage.

## Licensing and upstream acknowledgements

The release is a method built around enhanced frame sequences generated with third-party video restoration systems. It provides no SeedVR2 inference, model checkpoints or weights. The upstream creators retain all rights to their models and code; see [ATTRIBUTION.md](ATTRIBUTION.md).

The OSF-authored source and documentation are MIT (see LICENSE).
NumPy and OpenCV retain their respective upstream terms. No third-party
code, checkpoints, original photography or model weights are bundled.

For upstream dependency notices and the tested runtime context, see
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). An isolated temporary
Python 3.11 environment installed the exact pinned `requirements.txt` on
25 October 2026 and completed a native synthetic generate/run/verify
workflow. The current public test suite contains **19 engine tests and 21
source-inventory tests**; see GitHub Actions for actual per-commit results.
These checks are not full-shot creative approval.
