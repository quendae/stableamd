# StableAMD

StableAMD is a Windows-first local AI image-generation application focused on AMD Radeon GPUs. It keeps ComfyUI as an internal inference engine, but the normal user experience is a much smaller product UI with **Generate, Models, Gallery, Settings and Diagnostics**.

## Current status

StableAMD is currently a **v0.1 product candidate**. The application, packaging and clean-package bootstrap are implemented; the remaining release gate is running the packaged bootstrap and product acceptance flow end-to-end on the target RX 6950 XT.

The hardware feasibility path has already been proven on **AMD Radeon RX 6950 XT 16 GiB (`gfx1030`)**:

```text
RX 6950 XT -> TheRock multi-arch ROCm -> PyTorch -> ComfyUI -> SDXL 1024x1024
```

The validated reference run used:

- `device-gfx1030`;
- PyTorch `2.13.0+rocm10.1.0a20260822`;
- torchvision `0.28.0+rocm10.1.0a20260822` for the pinned product bootstrap;
- torchaudio `2.11.0+rocm10.1.0a20260822` for the pinned product bootstrap;
- ComfyUI `0.35.0`, pinned to commit `40c4fcdf513a4523e39d54a9d391908af8df8171`;
- Stable Diffusion XL 1.0 base;
- 1024x1024, 20 steps, batch 1;
- about 102 seconds and about 14 GiB peak VRAM on the tested RX 6950 XT.

The machine-readable release lock is in [`config/runtime-lock.v0.1.json`](config/runtime-lock.v0.1.json).

## What v0.1 contains

- managed loopback-only ComfyUI backend lifecycle;
- RX 6950 XT / `gfx1030` detection and diagnostics;
- StableAMD product API instead of arbitrary ComfyUI workflow execution;
- SDXL txt2img generation with prompt, negative prompt, model, size, steps, CFG and seed;
- local model discovery/import and Hugging Face checkpoint download;
- safetensors structural validation and optional SHA-256 verification;
- generation history and Gallery metadata;
- responsive local web UI;
- one-click Windows launcher;
- automatic first-launch bootstrap of private Python + the **pinned** TheRock ROCm/PyTorch stack + pinned ComfyUI when the runtime is missing;
- real FP16 Radeon compute verification before the bootstrapped runtime is accepted;
- source-only ZIP packaging that deliberately excludes runtimes, models and generated data;
- an isolated clean-package acceptance harness that does not touch the development runtime.

All services bind to `127.0.0.1`; v0.1 does not expose remote access, telemetry or cloud upload.

## Start StableAMD

Double-click:

```text
Start-StableAMD.cmd
```

or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Launch-StableAMD.ps1
```

If the managed runtime is missing, the launcher invokes `Install-StableAMDRuntime.ps1`. The first launch downloads a private Python 3.12.10 installation, the locked TheRock `gfx1030` package set and ComfyUI source, installs ComfyUI dependencies without allowing PyPI to replace the locked AMD torch family, then runs the existing FP16 GPU probe. This can download more than 1 GB.

If the runtime already exists, StableAMD reuses it. The launcher then starts or reuses the managed compute backend, starts the application server, waits for `/api/health`, writes logs under `.runtime\stableamd\logs`, and opens the local UI.

To prevent automatic runtime installation while diagnosing a machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Launch-StableAMD.ps1 -SkipRuntimeInstall
```

## Models

StableAMD can register/import local `.safetensors` checkpoints and download a file from Hugging Face through the product model flow. Existing SwarmUI Stable Diffusion model folders can also be discovered when present.

The official SDXL 1.0 base checkpoint is the v0.1 compatibility reference. LoRA, ControlNet, inpainting, Flux and video generation are intentionally deferred.

## Useful commands

```powershell
# Show exactly what the clean runtime bootstrap would install; no downloads
powershell -ExecutionPolicy Bypass -File .\scripts\Install-StableAMDRuntime.ps1 -PlanOnly

# Install or reuse the pinned Radeon runtime
powershell -ExecutionPolicy Bypass -File .\scripts\Install-StableAMDRuntime.ps1

# Runtime status
powershell -ExecutionPolicy Bypass -File .\scripts\Get-StableAMDStatus.ps1

# Stop the managed backend
powershell -ExecutionPolicy Bypass -File .\scripts\Stop-StableAMD.ps1

# List/discover models
powershell -ExecutionPolicy Bypass -File .\scripts\List-Models.ps1

# Build the source-only v0.1 package
powershell -ExecutionPolicy Bypass -File .\scripts\Build-StableAMDPackage.ps1

# Build a fresh package and resolve its install plan without downloading runtime files
powershell -ExecutionPolicy Bypass -File .\scripts\Test-StableAMDPackage.ps1 -PlanOnly

# Full isolated clean-package runtime acceptance on the Radeon machine
powershell -ExecutionPolicy Bypass -File .\scripts\Test-StableAMDPackage.ps1
```

The package builder produces:

```text
dist\StableAMD-0.1.0\
dist\StableAMD-0.1.0.zip
```

`.runtime`, model checkpoints, generated images, diagnostics, tests and Git metadata are not shipped inside that ZIP. The full package acceptance harness builds a fresh copy under `diagnostics\acceptance-package-*`, gives it separate local ports, installs its own runtime, verifies `/api/health` and the managed backend, then removes the successful isolated runtime unless `-KeepRuntime` is supplied. Failed acceptance directories are kept for diagnosis.

## Development and validation

The automated CI suite covers PowerShell parsing, Python API contracts, runtime/model/generation/frontend contracts, launcher behavior, packaging, the exact no-network runtime plan and a real plan-only package build. GPU/runtime downloads are intentionally not performed on GitHub-hosted runners.

The final target-machine procedure is in [`docs/v0.1-validation.md`](docs/v0.1-validation.md). The earlier feasibility work remains in [`docs/RX6950XT-SWARMUI-SPIKE.md`](docs/RX6950XT-SWARMUI-SPIKE.md).

Product design and implementation plan:

- [`docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md`](docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md)
- [`docs/superpowers/plans/2026-09-11-stableamd-v0.1.md`](docs/superpowers/plans/2026-09-11-stableamd-v0.1.md)

## Scope after v0.1

Later work can add more Radeon GPU targets, LoRA/ControlNet, additional model families and potentially WSL2/Linux backends. DirectML and ZLUDA remain explicit fallback investigations rather than silent defaults.
