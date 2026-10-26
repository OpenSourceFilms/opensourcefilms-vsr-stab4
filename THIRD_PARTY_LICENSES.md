# Runtime dependencies, provenance and redistribution notes

**Required upstream attribution:** STAB4 is an experimental OSF post-processor applied to separately generated enhanced image frames, commonly from ByteDance Seed's SeedVR2 model. The AI upscaling technology and its ComfyUI implementations are third-party work. See [ATTRIBUTION.md](ATTRIBUTION.md), including named authors and original projects.

- SeedVR / SeedVR2: ByteDance Seed research, https://github.com/ByteDance-Seed/SeedVR (upstream source states Apache-2.0). The independent pretrained model, inference stack and output rights must be checked separately.
- ComfyUI-SeedVR2 VideoUpscaler: NumZ, Adrien Toupet (AInVFX) and community contributors, https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler (Apache-2.0). **Not vendored or required by STAB4.**
- OpenCV DIS optical flow and NumPy numerical operations are existing third-party foundations, not OSF inventions.

This package distributes **OSF-authored post-processing/wrapper source code only**, under the
[MIT License](LICENSE). It does not contain camera footage, training data,
third-party weights, OpenCV or NumPy binaries.

## Direct runtime dependencies

| Component | Version/rights evidence | Packaging qualification |
|---|---|---|
| Python | Tested with CPython 3.11.13 | Standard library is used for manifests, hashing, tests and synthetic inputs |
| NumPy | Tested import version 1.26.4; core source uses BSD-3-Clause | Binary wheels can include additional third-party components/licences; see the installed wheel notices |
| OpenCV | Tested `cv2.__version__ == 4.11.0`; OpenCV 4.5.0+ is Apache-2.0 | `opencv-python` packaging is MIT; its wheels have additional FFmpeg/Qt and other notices |

Authoritative project licensing sources (checked 25 October 2026):

- [OpenCV library license](https://opencv.org/license/)
- [OpenCV Python wheel licensing notes](https://github.com/opencv/opencv-python#licensing)
- [NumPy licensing metadata](https://github.com/numpy/numpy/blob/main/pyproject.toml)

**Important:** the OSF ComfyGeneral environment used for this test contained
both `opencv-python` 4.11.0.86 and `opencv-python-headless` 4.13.0.92
distribution metadata. The imported `cv2` module identified as 4.11.0.
This is an existing shared research environment, *not* proof that a fresh
installation with either distribution will reproduce all test results. For a
new environment, install **one** appropriate OpenCV wheel family and verify
that `cv2.DISOpticalFlow_create` is present; do not intentionally mix the
headless and GUI variants. Keep all wheel license notices.

## Publication/usage boundaries

- MIT covers only the source authored and published by OSF.
- No third-party models, inference packages, checkpoints or pretrained data
  are distributed.
- You are responsible for observing the license terms of runtime binary
  distributions and any model used to generate the enhanced input sequence.
- Source code license clearance is not a guarantee that an enhanced output
  sequence may be used commercially: models, original footage, likenesses
  and underlying assets may impose independent restrictions.
- The synthetic tests do not qualify temporal visual quality or creative
  acceptance, especially around cuts, fast motion and occlusion.

## Independent clean-install qualification (25 October 2026)

In addition to the shared research environment described above, OSF installed
**only** the two pinned packages into a disposable, clean Python 3.11 venv:
`numpy==1.26.4` and `opencv-python-headless==4.11.0.86`. The imported
`cv2.__version__` was 4.11.0 and `DISOpticalFlow_create` was present.
All **15 synthetic tests passed** and synthetic 16×16 input / 32×32 enhanced
frames ran through probe, native 3-frame rendering and output verification
with `VERIFY_READY`. The disposable venv was deleted after acceptance.
This qualifies the pinned Python setup and synthetic execution, **not**
shot-specific visual quality, external model license, hardware portability
or any original photographic production data.
