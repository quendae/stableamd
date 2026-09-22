# StableAMD

StableAMD is a Windows-first local AI image-generation application focused on AMD Radeon GPUs. ComfyUI stays an internal inference engine while the normal user experience remains product-level: **Generate, Vector, Models, Gallery, Settings and Diagnostics**.

## Current status

The active development line is **StableAMD v0.3** on `feat/stableamd-v0.3` / draft PR #4.

The project is hardware-tested on an **AMD Radeon RX 6950 XT 16 GiB (`gfx1030`)** using the managed native-Windows TheRock/ROCm runtime. v0.3 is now a practical multi-provider Radeon image workstation with target-tested raster generation/editing plus a dedicated Clean SVG workflow.

Current detailed status: [`docs/v0.3-status.md`](docs/v0.3-status.md)  
Execution order: [`docs/v0.3-forward-plan.md`](docs/v0.3-forward-plan.md)  
Larger roadmap: [`docs/roadmap.md`](docs/roadmap.md)

### Accepted target hardware

```text
RX 6950 XT -> TheRock multi-arch ROCm -> PyTorch -> ComfyUI -> StableAMD
```

Locked runtime foundation:

- private CPython `3.12.10`;
- `device-gfx1030`;
- PyTorch `2.13.0+rocm10.1.0a20260822`;
- torchvision `0.28.0+rocm10.1.0a20260822`;
- torchaudio `2.11.0+rocm10.1.0a20260822`;
- pinned ComfyUI source managed by the StableAMD runtime installer.

Other Radeon GPUs are not implicitly validated by the RX 6950 XT result; each target still needs its own runtime/generation acceptance.

## Accepted model flows

### SDXL

The compatibility baseline remains supported:

- txt2img;
- img2img;
- inpaint;
- outpaint;
- ordered MultiLoRA;
- sampler/scheduler metadata and presets;
- external checkpoint and LoRA folders;
- Gallery history/reuse/delete.

SDXL is maintained, but new feature work now targets Z-Image Turbo and Krea 2 Turbo first.

### Z-Image Turbo

The dedicated Z-Image package uses:

- `z_image_turbo_bf16.safetensors`;
- `qwen_3_4b.safetensors`;
- `ae.safetensors`.

Target-accepted features include:

- repeated txt2img generation;
- one or multiple ordered model-only LoRAs;
- native Inpaint;
- native Outpaint through the accepted Union 2.1 Lite Fun Control patch;
- automatic Outpaint canvas preparation;
- Canny / OpenPose / Depth structural guidance;
- Gallery history/reuse/delete;
- classic `Upscale after`.

The proven sampler path remains `res_multistep + simple + CFG 1`.

### Krea 2 Turbo

The official FP8 package is accepted on the RX 6950 XT:

- `krea2_turbo_fp8_scaled.safetensors`;
- `qwen3vl_4b_fp8_scaled.safetensors`;
- `qwen_image_vae.safetensors`.

Target-accepted features include:

- txt2img through the dedicated `krea2-bundle` provider;
- official-style `8 steps / CFG 1 / Euler / simple` defaults;
- ordered model-only LoRA stacks;
- Gallery persistence/reuse;
- classic `Upscale after`;
- OpenPose structural control using the pinned Krea/Ostris edit integration and Turbo pose adapter;
- OpenPose + normal user LoRA in the same generation;
- Depth guidance;
- whole-image **Image Edit** using a source image plus a natural-language edit instruction.

Krea Image Edit follows the published reference-conditioning path rather than classic latent-denoise img2img:

```text
Source image
-> FluxKontextImageScale
-> TextEncodeKrea2OstrisEdit
-> FluxKontextMultiReferenceLatentMethod(index_timestep_zero)
-> Krea2OstrisEditModelPatch
-> KSampler
```

The output aspect is derived from the source image after `FluxKontextImageScale`. StableAMD therefore labels this mode **Image Edit** and does not expose a denoise slider for Krea.

## Control / pose guidance

StableAMD has a provider-aware control surface instead of pretending every model supports the same ControlNet graph.

Current accepted Krea 2 OpenPose path:

- pinned `ostris/ComfyUI-Krea2-Ostris-Edit` integration;
- pinned `krea2_turbo_openpose_controlnet.safetensors` adapter;
- curated pose templates;
- interactive OpenPose editor;
- safe-frame handling for Krea aspect ratios;
- user LoRA coexistence target-tested on the RX 6950 XT.

Z-Image control routes remain independently provider-aware and are documented in [`docs/v0.3-forward-plan.md`](docs/v0.3-forward-plan.md).

## LoRA compatibility

StableAMD does not assume that every discovered LoRA fits every model family.

Managed LoRA folders are grouped by family:

```text
.runtime\stableamd\models\loras\
├─ shared
├─ sd15
├─ sdxl
├─ sd3
├─ z-image
├─ flux
└─ krea
```

Safetensors metadata is inspected without loading tensor payloads, with managed-folder and filename hints used only as fallbacks. Known cross-family mismatches are blocked server-side; unknown adapters remain explicitly unknown instead of being guessed compatible.

Execution is workflow-specific:

- SDXL: model + CLIP LoRA path;
- Z-Image: model-only LoRA path;
- Krea 2: model-only LoRA path, matching the official Krea Turbo workflow.

## Editing and post-generation tools

Gallery and Generate expose the editing/upscale paths that the selected provider actually supports.

Accepted flows include:

- SDXL Img2Img / Inpaint / Outpaint;
- native Z-Image Inpaint / Outpaint;
- Krea 2 whole-image **Image Edit**;
- Gallery Reuse and Delete;
- `Upscale after` from Generate;
- manual Gallery upscale.

Krea Image Edit currently edits the whole reference image. Masked Krea editing and Image Edit + Control composition are intentionally separate future gates.

## Vector / Clean SVG

StableAMD has a dedicated **Vector** workspace with a security-bounded Clean SVG lifecycle. SVG output is sanitized before persistence and preview; arbitrary active SVG is never served directly to the browser.

### Text-to-SVG v1 — target-accepted

Text-to-SVG v1 is target-accepted on the physical RX 6950 XT as of 2026-09-22.

Accepted pipeline:

```text
Text prompt
-> constrained Z-Image Turbo raster source
-> release GPU runtime
-> optional border-connected background removal
-> VTracer 1.0.0-alpha.4
-> Clean SVG sanitizer
-> resvg_py 0.5.0 PNG preview
-> Vector Gallery record
```

The accepted product surface covers:

- Icon / Logo mark;
- Vector Illustration;
- Simple / Medium / Detailed tracing profiles;
- Auto / 2 / 4 / 8 / 16 color targets;
- transparent or solid background handling;
- Download SVG;
- safe View source;
- Reuse;
- Delete.

Physical acceptance included a two-color transparent fox icon and an 8-color multi-object vector illustration. The target session also confirmed Download SVG, View source, Reuse and Delete.

Acceptance record: [`docs/v0.3-text-to-svg-test.md`](docs/v0.3-text-to-svg-test.md)

### Image-to-SVG v1 — active implementation

Image-to-SVG is the next Vector feature. Its product/architecture design is locked in [`docs/superpowers/specs/2026-09-22-image-to-svg-v1-design.md`](docs/superpowers/specs/2026-09-22-image-to-svg-v1-design.md).

The design reuses the accepted VTracer / sanitizer / preview / Gallery stack and adds image-oriented source and preprocessing contracts.

Implemented source handoff:

- local image upload;
- raster Gallery `Convert to SVG`;
- current Generate / Image Edit result without download/re-upload.

Implemented modes:

```text
Artwork
Photo / Direct
Photo / Stylized / Preserve
Photo / Stylized / Creative
```

The default three non-Creative paths are deterministic and local. `Photo / Stylized / Creative` is provider-aware and uses the already accepted Krea whole-image Image Edit path first; if Krea is unavailable, only Creative is disabled.

The current Image-to-SVG form is compact: Source, Mode, Detail, Colors, Background, Crop and Convert to SVG. An Advanced section adds Smoothing, Edge strength, Denoise, Posterize and Background tolerance.

Crop behavior is `Preserve canvas` by default with optional `Auto-trim` and manual crop. Background is `Preserve` by default with optional border-connected transparent-background removal. Existing alpha is preserved.

Current implementation includes the dedicated async Image-to-SVG API, deterministic local preprocessing, Krea Creative capability gating, CPU-local vector job serialization, manual crop controls, Gallery Convert-to-SVG handoff and current-image handoff. Physical RX 6950 XT acceptance remains pending; worksheet: `docs/v0.3-image-to-svg-test.md`.

Image-to-SVG must not weaken the accepted Clean SVG allow-list or introduce a second SVG asset lifecycle.

## Classic upscale

The stable classic provider uses stock ComfyUI nodes:

```text
LoadImage -> UpscaleModelLoader -> ImageUpscaleWithModel -> SaveImage
```

Managed root:

```text
.runtime\stableamd\models\upscale_models\
```

Target-accepted curated models include:

- RealESRGAN x2plus;
- RealESRGAN x4plus;
- 4x-UltraSharp.

StableAMD can plan exact `2x`, `4x` and `8x` results by selecting a native matching model or chaining compatible x2/x4 passes. Curated downloads are size/hash verified before being promoted into the managed model folder.

## Runtime behavior

The current RX 6950 XT / 16 GiB default profile is:

```text
DynamicVRAM + RAM-pressure cache + CPU VAE
```

Provider-specific optimizations are applied only where target-tested. For example, Krea reference/edit paths can move the VAE work to `gpu:0` without globally removing the CPU-VAE safeguard used by other workflows.

Generation uses an asynchronous product transport:

```text
submit job -> poll status -> fetch result
```

Long Krea jobs therefore do not keep one browser request open for the entire generation. The GUI also waits for initial supported-model discovery before revealing the main interface, preventing model entries such as Krea from appearing a few seconds after the page is already usable.

## Start StableAMD

Double-click:

```text
Start-StableAMD.cmd
```

or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Launch-StableAMD.ps1
```

To pull the newest branch state and start in one step:

```text
Update-and-Start-StableAMD.cmd
```

If the managed runtime is missing, the launcher invokes the runtime installer. The backend and application bind to loopback only. Logs are written under `.runtime\stableamd\logs` and the supervisor owns process lifecycle/cleanup.

## Model packages and folders

The Models page is package-first:

- checkpoint models appear as logical packages;
- modern multi-file providers such as Z-Image and Krea 2 appear as one model entry;
- incomplete known packages remain visible with Found/Missing state;
- only ready + supported models are offered for generation;
- raw checkpoint / diffusion model / text encoder / VAE / LoRA roots stay available under advanced controls;
- curated provider dependencies can be installed through verified product flows where implemented.

Existing model libraries can be referenced without copying multi-gigabyte files. StableAMD generates the required `extra_model_paths.yaml` entries for configured roots and managed asset folders.

## Useful commands

```powershell
# Show what a clean runtime bootstrap would install; no downloads
powershell -ExecutionPolicy Bypass -File .\scripts\Install-StableAMDRuntime.ps1 -PlanOnly

# Install or reuse the pinned Radeon runtime
powershell -ExecutionPolicy Bypass -File .\scripts\Install-StableAMDRuntime.ps1

# Runtime status
powershell -ExecutionPolicy Bypass -File .\scripts\Get-StableAMDStatus.ps1

# Stop StableAMD managed processes
powershell -ExecutionPolicy Bypass -File .\scripts\Stop-StableAMD.ps1

# List/discover checkpoint models
powershell -ExecutionPolicy Bypass -File .\scripts\List-Models.ps1

# List logical multi-file model packages
powershell -ExecutionPolicy Bypass -File .\scripts\List-BundleModels.ps1

# Build the source package
powershell -ExecutionPolicy Bypass -File .\scripts\Build-StableAMDPackage.ps1

# Resolve a clean package install plan without downloading runtime files
powershell -ExecutionPolicy Bypass -File .\scripts\Test-StableAMDPackage.ps1 -PlanOnly
```

## Development and validation

CI covers PowerShell parsing, Python API contracts, Pester unit/regression tests, workflow construction, provider/model-root handling, frontend contracts, source package build and artifact upload.

Text-to-SVG was developed with explicit RED/GREEN coverage for the dependency manager, request semantics, VTracer execution, sanitizer/security boundaries, preview rendering, async orchestration, Gallery lifecycle and Vector frontend. The physical sanitizer compatibility issue found on the RX 6950 XT was reproduced in RED and fixed before the final target acceptance.

Image-to-SVG will follow the same TDD discipline. Its design requires separate automated coverage for managed source resolution, alpha/crop/background behavior, deterministic preprocessing, Creative capability gating, Krea adapter orchestration, ownership-aware cleanup and Gallery/current-result handoff.

Useful project documents:

- [`docs/v0.3-status.md`](docs/v0.3-status.md) — current accepted/pending v0.3 status;
- [`docs/v0.3-forward-plan.md`](docs/v0.3-forward-plan.md) — current execution order;
- [`docs/v0.3-text-to-svg-test.md`](docs/v0.3-text-to-svg-test.md) — target Text-to-SVG acceptance record;
- [`docs/superpowers/specs/2026-09-22-image-to-svg-v1-design.md`](docs/superpowers/specs/2026-09-22-image-to-svg-v1-design.md) — locked Image-to-SVG v1 architecture/product design;
- [`docs/roadmap.md`](docs/roadmap.md) — larger product directions;
- [`docs/v0.1-validation.md`](docs/v0.1-validation.md) — original clean-runtime RX 6950 XT acceptance;
- [`docs/RX6950XT-SWARMUI-SPIKE.md`](docs/RX6950XT-SWARMUI-SPIKE.md) — early feasibility work.

## Near-term roadmap

1. implement Image-to-SVG v1 on the accepted Vector foundation;
2. complete automated RED/GREEN and physical RX 6950 XT acceptance for Artwork, Direct, Stylized Preserve and Stylized Creative;
3. continue the separate Character Sheet v2 identity/stability physical gate without changing accepted global Krea defaults;
4. evaluate infographic-oriented generation after Image-to-SVG, prioritizing text fidelity, layout and editable structure;
5. keep Gaussian Splatting and video as post-v0.3 work.

Image-to-SVG v1 implementation is now active against the locked design; physical acceptance remains pending. Acceptance worksheet: `docs/v0.3-image-to-svg-test.md`.

The stable RX 6950 XT path takes priority over marginal throughput experiments that risk regressing already accepted workflows.
