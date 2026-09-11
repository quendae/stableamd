# SwarmUI RX 6950 XT Spike Design

## Goal

Validate whether SwarmUI's current Windows AMD path can run reliably enough on a Radeon RX 6950 XT 16 GB (`gfx1030`) to justify using SwarmUI as StableAMD's foundation.

## Support position

RX 6950 XT Windows support is treated as **experimental**. AMD's published Windows HIP SDK compatibility table does not list RX 6950 XT as supported for Runtime or HIP SDK, while TheRock currently builds and sanity-tests `gfx1030` on Windows. Therefore StableAMD must verify the actual machine instead of assuming support from architecture alone.

SwarmUI itself documents Windows AMD support as recent, limited to a subset of modern GPUs, and mentions `HSA_OVERRIDE_GFX_VERSION=10.3.0` as a workaround some Radeon users need.

## Scope of this spike

This spike does not build the final StableAMD UI. It adds a repeatable diagnostic and SwarmUI bootstrap path that answers four questions:

1. Does Windows correctly expose the RX 6950 XT and current AMD driver?
2. Can the current SwarmUI release start on the machine?
3. Can SwarmUI install/start its AMD ComfyUI backend?
4. Can the embedded ROCm/PyTorch runtime execute a real FP16 tensor operation on the GPU?

A successful spike is enough to proceed to a StableAMD fork/shell based on SwarmUI. A failure should produce diagnostics detailed enough to decide between a targeted `gfx1030` fix, WSL2/Linux backend, or another fallback.

## Architecture

The repository remains a thin StableAMD project. SwarmUI is **not vendored yet**. A bootstrap script clones a pinned upstream release into `.runtime/SwarmUI`, keeping experimental runtime files out of source control.

The spike is split into focused pieces:

- `scripts/StableAmd.Hardware.psm1` — pure helper functions for GPU identification and support classification.
- `scripts/Test-AmdPreflight.ps1` — records GPU, Windows, AMD driver, and toolchain information.
- `scripts/Install-SwarmSpike.ps1` — clones/pins SwarmUI and launches it either as a baseline run or with the `gfx1030` override.
- `scripts/Test-SwarmBackend.ps1` — interrogates SwarmUI's embedded ComfyUI Python environment and runs a small FP16 GPU compute test.
- `tests/StableAmd.Hardware.Tests.ps1` — Pester tests for hardware-name mapping and support-tier behavior.
- `diagnostics/` — local reports, excluded from git.
- `.runtime/` — local SwarmUI checkout, excluded from git.

## Test matrix

Two backend configurations are intentionally tested separately:

### A. Baseline

No `HSA_OVERRIDE_GFX_VERSION` is set. This determines whether current SwarmUI/ComfyUI packages recognize the 6950 XT without compatibility hacks.

### B. gfx1030 override

`HSA_OVERRIDE_GFX_VERSION=10.3.0` is set before SwarmUI/ComfyUI starts. This is only tested if baseline fails or is unstable.

The override must never silently become the product default without the baseline result being recorded.

## Preflight report

The preflight JSON records:

- Windows edition/version/build
- GPU names
- GPU driver versions
- detected StableAMD gfx target
- support tier (`experimental-windows` for RX 6950 XT)
- Git availability/version
- .NET availability/version
- Python launcher/interpreter availability
- `hipinfo`, `offload-arch`, or ROCm tools if already on PATH
- whether `HSA_OVERRIDE_GFX_VERSION` is already set

The script must not install or change drivers.

## SwarmUI bootstrap

The bootstrap defaults to the currently selected SwarmUI release ref and clones it beneath `.runtime/SwarmUI`. It may refresh that checkout only when explicitly requested.

It launches `launch-windows.bat` with `--launch_mode none`, preserving the terminal/log-oriented workflow. The child process inherits the optional `HSA_OVERRIDE_GFX_VERSION` value.

The script waits for the default HTTP endpoint on port `7801` and records whether the server becomes reachable. Initial SwarmUI setup remains in upstream's installer UI because modifying installer behavior before proving hardware viability adds unnecessary variables.

## Backend smoke test

After the user completes SwarmUI's AMD backend installation, `Test-SwarmBackend.ps1` locates:

`.runtime/SwarmUI/dlbackend/comfy/python_embeded/python.exe`

It runs a short Python probe that reports:

- Python version
- PyTorch version
- `torch.version.hip`
- `torch.cuda.is_available()` (PyTorch ROCm uses the CUDA-compatible API namespace)
- detected device name
- VRAM when available

If a GPU is available, it allocates two small FP16 tensors on the GPU, performs matrix multiplication, synchronizes, and records success/failure and elapsed time. This tests actual GPU computation rather than accepting package installation as proof.

## Success criteria

The spike passes when:

1. RX 6950 XT is detected as `gfx1030`.
2. SwarmUI starts and serves HTTP locally.
3. The AMD ComfyUI backend installs and starts without CPU fallback.
4. PyTorch reports a HIP runtime and GPU availability.
5. The FP16 tensor test executes successfully on the Radeon device.
6. A manual 1024x1024 SDXL generation can be completed in SwarmUI after installing a model.

Only after these checks should StableAMD begin modifying/forking SwarmUI's UI and model-management experience.

## Failure policy

A failure must preserve diagnostics and should not automatically switch to DirectML, ZLUDA, WSL2, or CPU. Fallback selection is a deliberate follow-up decision based on the failure point.

## Product direction after a successful spike

StableAMD will use SwarmUI as the practical base, while simplifying the default experience around four primary surfaces: Generate, Models, Gallery, and Settings. Raw Comfy workflows remain available as an advanced mode rather than the normal workflow.
