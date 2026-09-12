# StableAMD

StableAMD is a Windows-first local AI image-generation application focused on AMD Radeon GPUs. It keeps ComfyUI as an internal inference engine while the normal user experience stays product-level: **Generate, Models, Gallery, Settings and Diagnostics**.

## Current status

StableAMD v0.1 is **hardware-accepted on AMD Radeon RX 6950 XT 16 GiB (`gfx1030`)**. The target-machine acceptance completed on 2026-09-11 covered a fresh source-package runtime bootstrap, native Radeon FP16 compute, managed ComfyUI and application startup, recursive external model discovery, SDXL 1024x1024 generation through StableAMD, output persistence and Gallery display.

```text
RX 6950 XT -> TheRock multi-arch ROCm -> PyTorch -> ComfyUI -> StableAMD -> SDXL 1024x1024
```

The accepted locked stack is:

- private CPython `3.12.10` from the CPython NuGet x64 package;
- `device-gfx1030`;
- PyTorch `2.13.0+rocm10.1.0a20260822`;
- torchvision `0.28.0+rocm10.1.0a20260822`;
- torchaudio `2.11.0+rocm10.1.0a20260822`;
- ComfyUI `0.35.0`, pinned to commit `40c4fcdf513a4523e39d54a9d391908af8df8171`;
- Stable Diffusion XL 1.0 base as the compatibility reference.

The earlier feasibility reference run at 1024x1024 / 20 steps used about 102 seconds and about 14 GiB peak VRAM on the tested RX 6950 XT. The machine-readable runtime lock and acceptance state are in [`config/runtime-lock.v0.1.json`](config/runtime-lock.v0.1.json).

Other Radeon GPUs are not implicitly validated by this result; each target needs its own runtime/generation acceptance.

## What v0.1 contains

- managed loopback-only ComfyUI backend lifecycle;
- RX 6950 XT / `gfx1030` detection and diagnostics;
- StableAMD product API instead of arbitrary ComfyUI workflow execution;
- SDXL txt2img generation with prompt, negative prompt, model, size, steps, CFG and seed;
- recursive model-folder discovery that uses existing checkpoints in place without copying them;
- optional single-file local import plus Hugging Face checkpoint download;
- safetensors structural validation and optional SHA-256 verification;
- generation history and Gallery metadata;
- responsive local web UI;
- one-click Windows launcher;
- automatic first-launch bootstrap of private CPython + the pinned TheRock ROCm/PyTorch stack + pinned ComfyUI;
- real FP16 Radeon compute verification before a bootstrapped runtime is accepted;
- source-only ZIP packaging that deliberately excludes runtimes, models and generated data;
- isolated clean-package acceptance that does not touch the development runtime.

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

If the managed runtime is missing, the launcher invokes `Install-StableAMDRuntime.ps1`. First launch downloads the private CPython 3.12.10 NuGet runtime, the locked TheRock `gfx1030` package set and pinned ComfyUI source, installs ComfyUI dependencies without allowing PyPI to replace the locked AMD torch family, then runs the Radeon FP16 compute probe. This can download more than 1 GB.

If the runtime already exists, StableAMD reuses it. The launcher then starts or reuses the managed compute backend, starts the application server, waits for `/api/health`, writes logs under `.runtime\stableamd\logs`, and opens the local UI.

To prevent automatic runtime installation while diagnosing a machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Launch-StableAMD.ps1 -SkipRuntimeInstall
```

## Models

The recommended local workflow is **Models -> Add folder -> Scan models**. StableAMD stores selected Windows folders in its local configuration, scans them recursively for `.safetensors` checkpoints and passes them directly to ComfyUI through generated `extra_model_paths.yaml`. Multi-gigabyte checkpoints stay in their original location and are not copied.

Use **Browse folder...** to open the native Windows folder picker, or paste a path such as `D:\AI\Models`. Adding or removing a folder refreshes the managed backend when needed so ComfyUI sees the new search path. Existing SwarmUI Stable Diffusion folders are also discovered when present.

Single-file copy/move import and resumable Hugging Face download remain available under **Other ways to add models**.

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

# List configured model folders
powershell -ExecutionPolicy Bypass -File .\scripts\Get-ModelRoots.ps1

# Add an existing model library without copying it
powershell -ExecutionPolicy Bypass -File .\scripts\Add-ModelRoot.ps1 -Path 'D:\AI\Models'

# Build the source-only v0.1 package
powershell -ExecutionPolicy Bypass -File .\scripts\Build-StableAMDPackage.ps1

# Resolve a clean package install plan without downloading runtime files
powershell -ExecutionPolicy Bypass -File .\scripts\Test-StableAMDPackage.ps1 -PlanOnly

# Repeat the full isolated clean-package GPU/runtime acceptance
powershell -ExecutionPolicy Bypass -File .\scripts\Test-StableAMDPackage.ps1
```

The package builder produces:

```text
dist\StableAMD-0.1.0\
dist\StableAMD-0.1.0.zip
```

`.runtime`, model checkpoints, generated images, diagnostics, tests and Git metadata are not shipped inside that ZIP. The full package acceptance harness builds a fresh copy under `diagnostics\acceptance-package-*`, gives it separate local ports, installs its own runtime, verifies FP16 compute plus application/backend health, then removes the successful isolated runtime unless `-KeepRuntime` is supplied. Failed acceptance directories are kept for diagnosis.

## Development and validation

The automated CI suite covers PowerShell parsing, Python API contracts, runtime/model/generation/frontend contracts, Windows PowerShell 5.1 compatibility, external model-folder configuration, launcher behavior, generated-output correlation, packaging, the exact no-network runtime plan and a real plan-only package build. GPU/runtime downloads are intentionally not performed on GitHub-hosted runners.

Target-machine evidence and repeatable acceptance commands are in [`docs/v0.1-validation.md`](docs/v0.1-validation.md). The earlier feasibility work remains in [`docs/RX6950XT-SWARMUI-SPIKE.md`](docs/RX6950XT-SWARMUI-SPIKE.md).

Product design and implementation plan:

- [`docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md`](docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md)
- [`docs/superpowers/plans/2026-09-11-stableamd-v0.1.md`](docs/superpowers/plans/2026-09-11-stableamd-v0.1.md)

## Scope after v0.1

Later work can add more Radeon GPU targets, LoRA/ControlNet, additional model families and potentially WSL2/Linux backends. DirectML and ZLUDA remain explicit fallback investigations rather than silent defaults.
