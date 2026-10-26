# Upstream credits and scope of this release

**STAB4 is not an AI upscaling model, nor an implementation of the SeedVR/SeedVR2 neural networks.** It is an experimental post-processing application of other researchers' video restoration work to a particular filmmaking problem. Its temporal treatment is only useful when suitable source and enhanced frame sequences are supplied; the repository contains no model, model weights, inference code, generated footage or third-party vendored source.

## Primary upstream video-restoration research

- **SeedVR**: *Seeding Infinity in Diffusion Transformer Towards Generic Video Restoration* (CVPR 2025), by Jianyi Wang, Zhijie Lin, Meng Wei, Yang Zhao, Ceyuan Yang, Chen Change Loy and Lu Jiang. Project: https://github.com/ByteDance-Seed/SeedVR
- **SeedVR2**: *One-Step Video Restoration via Diffusion Adversarial Post-Training* (ICLR 2026), by Jianyi Wang, Shanchuan Lin, Zhijie Lin, Yuxi Ren, Meng Wei, Zongsheng Yue, Shangchen Zhou, Hao Chen, Yang Zhao, Ceyuan Yang, Xuefeng Xiao, Chen Change Loy and Lu Jiang. Official ICLR 2026 paper: https://proceedings.iclr.cc/paper_files/paper/2026/hash/444d69470b24ded080183c907b711bbf-Abstract-Conference.html . Project and citation: https://github.com/ByteDance-Seed/SeedVR
- The upstream researchers and their organisations developed the generative restoration models that produce the enhanced inputs used in OSF's SeedVR2-based experiments. The STAB4 package **does not** train, provide or replace those models.
- The public upstream SeedVR / SeedVR2 source repository states **Apache-2.0**. Model files, inference dependencies and generated media may have separate applicable terms that users must independently check.

## ComfyUI integration

- **ComfyUI-SeedVR2_VideoUpscaler**, by NumZ, Adrien Toupet (AInVFX) and community contributors: https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler (Apache-2.0 repository).
- ComfyUI and its community make the upstream video-restoration models usable in graph-based workflows. This STAB4 package does not vendor or require that custom node: you supply enhanced image sequences produced elsewhere.
- Any actual upstream ComfyUI workflow or model in a user's pipeline remains third-party work subject to its own licence and attribution.

## Numerical and motion-estimation foundations

- **OpenCV**: DIS optical flow and image processing, https://opencv.org/ (OpenCV 4.5+ Apache-2.0; separately licensed packaging components may apply).
- **NumPy**: Numerical arrays and computation, https://numpy.org/ (BSD-3-Clause for NumPy core; consult distribution notices).

## OSF's contribution and limits

Open Source Films assembled, tested and documented the frozen **radius-four temporal-stabilisation post-processing implementation**, with source-frame optical flow, frame mapping, processing guards, integrity manifests, resume and native-output verification. Those are the repository's distributable OSF-authored components. **OSF does not claim authorship of SeedVR, SeedVR2, their pretrained models, the ComfyUI integrations, optical-flow algorithms or the underlying numerical libraries.**

The MIT licence supplied in this repository applies only to the original OSF-authored package files. It does not relicense any external source, model, weights, video or input imagery. The package is experimental, has known potential motion smear and has not obtained full-shot visual acceptance. Not affiliated with, endorsed by, or an official release of the upstream researchers or projects.

Upstream references and licence claims were checked on 26 October 2026; verify upstream releases and conditions when using their material.
