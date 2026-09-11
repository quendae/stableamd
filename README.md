# StableAMD

StableAMD is a Windows-first local AI image-generation application focused on AMD Radeon GPUs. It keeps ComfyUI as an internal inference engine, but the normal user experience is a much smaller product UI with **Generate, Models, Gallery, Settings and Diagnostics**.

## Current status

StableAMD is currently a **v0.1 product candidate**, not a finished clean-machine release.

The hardware feasibility path has already been proven on **AMD Radeon RX 6950 XT 16 GiB (`gfx1030`)**:

```text
RX 6950 XT -> TheRock multi-arch ROCm -> PyTorch -> ComfyUI -> SDXL 1024x1024
```

The validated reference run used:

- `device-gfx1030`;
- PyTorch `2.13.0+rocm10.1.0a20260822`;
- ComfyUI `0.35.0`;
- Stable Diffusion XL 1.0 base;
- 1024x1024, 20 steps, batch 1;
- about 102 seconds and about 14 GiB peak VRAM on the tested RX 6950 XT.

The exact release lock is in [`config/runtime-lock.v0.1.json`](config/runtime-lock.v0.1.json).

## What v0.1 already contains

- managed loopback-only ComfyUI backend lifecycle;
- RX 6950 XT / `gfx1030` detection and diagnostics;
- StableAMD product API instead of arbitrary ComfyUI workflow execution;
- SDXL txt2img generation with prompt, negative prompt, model, size, steps, CFG and seed;
- local model discovery/import and Hugging Face checkpoint download;
- safetensors structural validation and optional SHA-256 verification;
- generation history and Gallery metadata;
- responsive local web UI;
- one-click Windows launcher for an already prepared validated runtime;
- source-only ZIP packaging that deliberately excludes runtimes, models and generated data.

All services bind to `127.0.0.1`; v0.1 does not expose remote access, telemetry or cloud upload.

## Start StableAMD

On a machine where the validated TheRock + ComfyUI runtime is already present under `.runtime`, double-click:

```text
Start-StableAMD.cmd
```

or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Launch-StableAMD.ps1
```

The launcher starts or reuses the managed compute backend, starts the StableAMD application server, waits for `/api/health`, writes logs under `.runtime\stableamd\logs`, and opens the local UI.

### Fresh-machine limitation

The remaining v0.1 release gate is **clean-machine runtime installation/reuse**. The current launcher intentionally does not silently replace the proven TheRock environment with an unvalidated package combination. Final packaging is therefore still pre-release until the clean-machine bootstrap is exercised on the RX 6950 XT end-to-end.

See [`docs/v0.1-validation.md`](docs/v0.1-validation.md) for the exact acceptance checklist.

## Models

StableAMD can register/import local `.safetensors` checkpoints and download a file from Hugging Face through the product model flow. Existing SwarmUI Stable Diffusion model folders can also be discovered when present.

The official SDXL 1.0 base checkpoint is the v0.1 compatibility reference. LoRA, ControlNet, inpainting, Flux and video generation are intentionally deferred.

## Useful commands

```powershell
# Runtime status
powershell -ExecutionPolicy Bypass -File .\scripts\Get-StableAMDStatus.ps1

# Start only the managed ComfyUI backend
powershell -ExecutionPolicy Bypass -File .\scripts\Start-StableAMD.ps1

# Stop the managed backend
powershell -ExecutionPolicy Bypass -File .\scripts\Stop-StableAMD.ps1

# List/discover models
powershell -ExecutionPolicy Bypass -File .\scripts\List-Models.ps1

# Build the source-only v0.1 package
powershell -ExecutionPolicy Bypass -File .\scripts\Build-StableAMDPackage.ps1
```

The package builder produces:

```text
dist\StableAMD-0.1.0\
dist\StableAMD-0.1.0.zip
```

`.runtime`, model checkpoints, generated images, diagnostics, tests and Git metadata are not shipped inside that ZIP.

## Development and validation

The product design and implementation plan are in:

- [`docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md`](docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md)
- [`docs/superpowers/plans/2026-09-11-stableamd-v0.1.md`](docs/superpowers/plans/2026-09-11-stableamd-v0.1.md)
- [`docs/v0.1-validation.md`](docs/v0.1-validation.md)

The original Windows AMD feasibility work remains documented in [`docs/RX6950XT-SWARMUI-SPIKE.md`](docs/RX6950XT-SWARMUI-SPIKE.md).

## Scope after v0.1

Later work can add more Radeon GPU targets, stronger automatic runtime installation/repair, LoRA/ControlNet, additional model families and potentially WSL2/Linux backends. DirectML and ZLUDA remain explicit fallback investigations rather than silent defaults.
