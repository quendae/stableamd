# StableAMD roadmap

Last updated: 2026-09-16

This file tracks larger product directions. Detailed implementation/acceptance state for the active release remains in `docs/v0.3-status.md`; the active execution order lives in `docs/v0.3-forward-plan.md`.

## v0.3 — active

Primary goal: turn the proven Radeon/ComfyUI runtime into a practical multi-provider image workstation without destabilizing the accepted RX 6950 XT path.

Already target-accepted in v0.3:

- Z-Image Turbo txt2img + ordered model-only LoRA;
- native Z-Image Inpaint / Outpaint;
- Krea 2 Turbo txt2img + model-only LoRA;
- Krea 2 OpenPose, including normal user-LoRA coexistence;
- Krea 2 whole-image Image Edit;
- curated pose templates + interactive pose editor;
- classic verified upscaling with exact 2x/4x/8x planning;
- asynchronous long-generation jobs;
- capability-aware model/mode UI and startup model-discovery gate.

Current order:

1. Finish remaining provider-aware structural guidance:
   - Z-Image control-route acceptance;
   - Krea Depth;
   - automatic pose extraction from a normal source photo.
2. Expand the accepted Krea Image Edit route:
   - material/texture replacement;
   - one/two-image reference roles;
   - character turnaround sheets;
   - later masked Krea editing and Image Edit + Control composition if target-stable.
3. Add vector/graphics workflows:
   - text-to-SVG;
   - image-to-SVG;
   - infographic-specialized generation/tooling.
4. Finish remaining v0.3 polish and infrastructure that directly supports these workflows.

SDXL remains the compatibility baseline but is no longer the main feature-development target. Inpaint/outpaint are maintained, while new provider work prioritizes Z-Image and Krea.

## v0.4 candidate — Image(s) to Gaussian Splat

Add Gaussian Splatting as a separate 3D tool rather than mixing it into the image-generation provider contract.

### Intended UX

- new `3D / Gaussian Splat` tool;
- accept one or multiple source images;
- `Object` and `Scene` modes;
- optional background removal for isolated objects;
- generate a splat locally;
- interactive orbit/zoom preview in the StableAMD web UI;
- export a portable splat/PLY representation;
- preserve source images/settings in Gallery/history.

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

This feature remains intentionally **post-v0.3** so it does not delay the current image workstation.

## Later — video generation

Video comes after the v0.3 image workstation and first 3D work. It needs its own queue/job lifecycle, preview/export UX and memory/runtime acceptance. Candidate models should be selected by demonstrated Windows/AMD feasibility rather than name recognition alone.
