# StableAMD

StableAMD is a Windows-first local AI image-generation application focused on AMD Radeon GPUs. ComfyUI stays an internal inference engine while the normal user experience remains product-level: **Generate, Models, Gallery, Settings and Diagnostics**.

## Current status

The active development line is **StableAMD v0.3** on `feat/stableamd-v0.3` / draft PR #4.

The original v0.1 runtime is hardware-accepted on an AMD Radeon RX 6950 XT 16 GiB (`gfx1030`). v0.3 extends that accepted native-Windows AMD stack with SDXL img2img/inpaint, model packages, Z-Image Turbo, model-aware LoRA handling and post-generation tools.

Current detailed status and roadmap: [`docs/v0.3-status.md`](docs/v0.3-status.md).

### Accepted target hardware

```text
RX 6950 XT -> TheRock multi-arch ROCm -> PyTorch -> ComfyUI -> StableAMD
```

Locked runtime:

- private CPython `3.12.10` from the CPython NuGet x64 package;
- `device-gfx1030`;
- PyTorch `2.13.0+rocm10.1.0a20260822`;
- torchvision `0.28.0+rocm10.1.0a20260822`;
- torchaudio `2.11.0+rocm10.1.0a20260822`;
- ComfyUI `0.35.0` pinned to `40c4fcdf513a4523e39d54a9d391908af8df8171`.

Other Radeon GPUs are not implicitly validated by the RX 6950 XT result; each target still needs its own runtime/generation acceptance.

## Working model flows

### SDXL

StableAMD currently supports:

- txt2img;
- img2img;
- inpainting execution;
- sampler/scheduler metadata and presets;
- ordered MultiLoRA;
- external checkpoint and LoRA folders;
- Gallery history/reuse.

### Z-Image Turbo

Z-Image Turbo is implemented as a dedicated official-style ComfyUI package using:

- `z_image_turbo_bf16.safetensors`;
- `qwen_3_4b.safetensors`;
- `ae.safetensors`.

The RX 6950 XT 16 GiB target has completed repeated generation tests. The recommended target profile is:

```powershell
.\Start-StableAMD.cmd -DisableDynamicVram -LowVram -CacheClassic
```

In the stable warm state, the tested 1024-class / 8-step profile runs at roughly `2.36-2.38 s/it`, with repeated same-prompt generations around `25-26 s` and a changed prompt around `32 s`. The Qwen text encoder stays on CPU and Lumina2 is partially resident in VRAM. `HighVram` is intentionally not the recommended 16 GiB path because full model residency was much slower in repeated target tests.

Z-Image now exposes four resolution tiers (`Small`, `1024`, `1280`, `1536`), common aspect-ratio presets and fast/recommended/quality step presets while keeping the proven `res_multistep + simple + CFG 1` path.

## LoRA compatibility

StableAMD no longer assumes that every discovered LoRA fits every model family.

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

The application reads safetensors metadata without loading tensor payloads, then falls back to managed-folder and filename hints. Known cross-family mismatches are blocked server-side; unknown adapters remain explicitly unknown rather than being guessed compatible.

Actual LoRA execution remains workflow-specific. SDXL LoRA/MultiLoRA is implemented; Z-Image LoRA execution is still planned.

## Post-generation tools

Gallery items expose:

- **Upscale**
- **Img2Img**
- **Inpaint**
- **Outpaint**

Img2Img and Inpaint hand off the generated image to the existing editors. Outpaint currently has the handoff/editor shell and still needs the final expanded-canvas geometry/execution pass.

### Classic upscale

The first upscaler is intentionally simple and independent of the diffusion family:

```text
LoadImage -> UpscaleModelLoader -> ImageUpscaleWithModel -> SaveImage
```

Put compatible models in:

```text
.runtime\stableamd\models\upscale_models\
```

The current implementation supports the stock ComfyUI `UpscaleModelLoader` contract and common ESRGAN-family model files such as RealESRGAN and 4x-UltraSharp. `RealESRGAN_x2plus.pth` is now discovered correctly on the RX 6950 XT target. The next target gate is the first successful end-to-end upscale after the latest workflow-service parameter fix.

SeedVR2 is planned as a separate optional/experimental provider, not as a dependency of the stable classic upscaler.

## Start StableAMD

Double-click:

```text
Start-StableAMD.cmd
```

or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Launch-StableAMD.ps1
```

If the managed runtime is missing, the launcher invokes `Install-StableAMDRuntime.ps1`. First launch downloads the private Python runtime, the locked TheRock `gfx1030` package set and pinned ComfyUI source, then verifies real Radeon FP16 compute before accepting the runtime.

The managed backend and application bind to loopback only. Logs are written under `.runtime\stableamd\logs` and the supervisor owns the process lifecycle so Ctrl+C/close can release the backend and VRAM cleanly.

For the currently proven Z-Image/RX 6950 XT memory profile:

```powershell
.\Start-StableAMD.cmd -DisableDynamicVram -LowVram -CacheClassic
```

## Model packages and folders

The Models page is package-first:

- single-file checkpoints appear as logical model packages;
- modern multi-file models such as Z-Image appear as one package with component readiness;
- incomplete known packages stay visible with Found/Missing status;
- only ready + supported models are offered for generation;
- raw checkpoint / diffusion model / text encoder / VAE / LoRA roots remain under advanced controls.

Existing model libraries can be referenced without copying multi-gigabyte files. StableAMD writes generated `extra_model_paths.yaml` entries for configured roots and managed asset folders.

## Useful commands

```powershell
# Show exactly what the clean runtime bootstrap would install; no downloads
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

CI covers PowerShell parsing, Python API contracts, Pester unit/regression tests, Windows PowerShell compatibility, workflow construction, model/root handling, frontend contracts, package build and artifact upload. GPU/runtime execution is still validated on the physical RX 6950 XT target rather than GitHub-hosted runners.

Useful project documents:

- [`docs/v0.3-status.md`](docs/v0.3-status.md) — current accepted/pending v0.3 status and roadmap;
- [`docs/v0.1-validation.md`](docs/v0.1-validation.md) — original clean-runtime RX 6950 XT acceptance;
- [`docs/superpowers/plans/2026-09-13-lora-upscale-edit-handoff.md`](docs/superpowers/plans/2026-09-13-lora-upscale-edit-handoff.md) — current post-generation implementation plan;
- [`docs/RX6950XT-SWARMUI-SPIKE.md`](docs/RX6950XT-SWARMUI-SPIKE.md) — early feasibility work.

## Near-term roadmap

1. finish RealESRGAN/stock upscale target acceptance and output/history integration;
2. complete Outpaint geometry and execution;
3. add curated one-click classic upscale model installation;
4. probe and benchmark optional SeedVR2 on 16 GiB AMD;
5. implement **Krea2** as the next major model family using the same package-first/provider architecture;
6. after Krea2, add batch/queue generation while preserving model residency, then revisit ControlNet/OpenPose and other useful families.

SageAttention/Triton-style attention optimizations are optional later experiments only. The stable path is prioritized over replacing a working configuration for marginal throughput gains.
