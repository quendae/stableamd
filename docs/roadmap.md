# StableAMD roadmap

Last updated: 2026-09-14

This file tracks larger product directions. Detailed implementation/acceptance state for the active release remains in `docs/v0.3-status.md`; the agreed execution order and feature backlog live in `docs/v0.3-forward-plan.md`.

## v0.3 — active

Primary goal: turn the proven Radeon/ComfyUI runtime into a practical multi-provider image workstation without destabilizing the accepted RX 6950 XT path.

Current order:

1. Curated one-click dependency installer, starting with the accepted Z-Image Union 2.1 Lite model patch.
2. Real Krea 2 LoRA execution and target acceptance, including stack/history/reuse behavior where the pinned loader path supports it.
3. ControlNet / structural guidance, beginning with Canny, Depth and OpenPose and keeping provider/model compatibility explicit.
4. First-class image-edit workflows: general image edit, material replacement, one/two-image reference and style guidance, then a character turnaround sheet preset.
5. Separate vector/graphics providers for text-to-SVG, image-to-SVG and infographic-specialized generation.
6. Remaining v0.3 polish and infrastructure that directly supports these workflows; inpaint/outpaint stay maintained but are no longer the main development focus.

Batch/queue work and optional SeedVR2 evaluation remain useful supporting work, but they do not take priority over installer -> Krea 2 LoRA -> ControlNet.

## v0.4 candidate — Image(s) to Gaussian Splat

Add Gaussian Splatting as a separate 3D tool rather than mixing it into the image-generation provider contract.

### Intended UX

- new `3D / Gaussian Splat` tool;
- accept one or multiple source images;
- `Object` and `Scene` modes;
- optional background removal for isolated objects;
- generate a splat locally;
- interactive orbit/zoom preview in the StableAMD web UI;
- export a portable splat/PLY representation and keep the result in Gallery/history with its source images and settings.

### Backend direction

For the Radeon/Windows product path, prefer a modern image-to-splat backend with a Vulkan-capable implementation, currently **FreeSplatter / free-splatter.cpp**, rather than making the original GraphDeco optimizer the primary integration target.

References:

- FreeSplatter: https://github.com/TencentARC/FreeSplatter
- Vulkan/C++ port: https://github.com/localai-org/free-splatter.cpp
- Original 3D Gaussian Splatting reference implementation: https://github.com/graphdeco-inria/gaussian-splatting

Rationale:

- original GraphDeco 3DGS is fundamentally a multi-view/SfM training pipeline and its reference optimizer is CUDA-oriented;
- the StableAMD feature should also be useful from a single photo, accepting that unseen geometry is inferred rather than observed;
- 2–8 views should be encouraged for substantially better geometry/appearance consistency;
- a Vulkan path is a much better fit for the project's Windows + Radeon goal than a new CUDA-to-ROCm porting project.

### First acceptance gate

1. One image -> splat on RX 6950 XT without NVIDIA/CUDA dependencies.
2. 2–4 image object test showing better unseen-side consistency than the single-image run.
3. Browser viewer capable of smooth orbit/zoom on the generated result.
4. Export and Gallery persistence.

This feature is intentionally **post-v0.3** so it does not delay the current image-model/provider work.

## Later — video generation

Video is intentionally after the core v0.3 image workstation and the first 3D work. It needs its own queue/job lifecycle, preview/export UX and memory/runtime acceptance. MiniMax H3 is the first candidate to benchmark on the target Radeon system; other models should be selected by demonstrated Windows/AMD feasibility rather than name recognition alone.
