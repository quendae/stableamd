# RX 6950 XT + SwarmUI Windows spike

This runbook validates the exact Windows + Radeon RX 6950 XT path before StableAMD forks or simplifies SwarmUI.

## Important support note

Treat RX 6950 XT (`gfx1030`) ROCm on Windows as experimental. AMD's Windows HIP SDK compatibility table currently does not mark RX 6950 XT as supported, even though TheRock builds and sanity-tests `gfx1030` on Windows. The point of this spike is to measure the real machine rather than assume support.

Do **not** start by setting `HSA_OVERRIDE_GFX_VERSION`. First record a clean baseline.

## 1. Clone the spike branch

```powershell
git clone -b spike/swarmui-rx6950xt https://github.com/quendae/stableamd.git
cd stableamd
```

If you already have the repository:

```powershell
git fetch
git switch spike/swarmui-rx6950xt
git pull
```

## 2. Run preflight

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test-AmdPreflight.ps1
```

Expected target lines include:

```text
GPU: AMD Radeon RX 6950 XT | ... | gfx1030 | experimental-windows
Next test should be Baseline mode, with no HSA_OVERRIDE_GFX_VERSION.
```

A JSON report is written to `diagnostics/preflight-*.json`.

Do not continue if the script does not identify the 6950 XT as `gfx1030`.

## 3. Start the SwarmUI baseline

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Install-SwarmSpike.ps1 -Mode Baseline
```

The script:

- clones the pinned SwarmUI release into `.runtime\SwarmUI`;
- removes any process-level `HSA_OVERRIDE_GFX_VERSION` for the child process;
- launches SwarmUI with `--launch_mode none`;
- waits for `http://127.0.0.1:7801/`;
- stores stdout, stderr and a launch report in `diagnostics\`.

Open:

```text
http://127.0.0.1:7801/
```

Complete SwarmUI's own installer. When prompted for the backend, select the AMD-compatible ComfyUI option.

For this first pass, do not customize the ComfyUI Python environment manually.

## 4. Run the backend GPU test

After SwarmUI finishes installing the AMD ComfyUI backend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test-SwarmBackend.ps1 -Mode Baseline
```

A passing result should show all of the following:

- a PyTorch version;
- a non-empty HIP version;
- `GPU available: True`;
- a Radeon device name;
- approximately 16 GiB VRAM;
- `FP16 matmul: True`.

The script performs actual FP16 matrix multiplication on the GPU and synchronizes the device. A package that installs but falls back to CPU does not pass this gate.

The report is saved as `diagnostics/backend-baseline-*.json`.

## 5. Only if baseline fails: gfx1030 compatibility override

Stop the existing SwarmUI process first, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Install-SwarmSpike.ps1 -Mode GfxOverride
```

This child process receives:

```text
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

After SwarmUI starts, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Test-SwarmBackend.ps1 -Mode GfxOverride
```

The override is a compatibility experiment, not a StableAMD default.

## 6. SDXL end-to-end gate

If the tensor test passes, use SwarmUI's Models interface to install a known SDXL checkpoint and generate one image with:

- resolution: `1024 x 1024`;
- batch: `1`;
- no ControlNet;
- no LoRA;
- no upscaler;
- ordinary SDXL text-to-image workflow.

Record:

- whether generation completed;
- generation time;
- peak VRAM if available;
- whether the process crashed or reset the AMD driver;
- whether the output was produced entirely with the Radeon backend.

Do not optimize performance yet. The first goal is correctness and stability.

## 7. What to share after the test

The useful files are:

```text
diagnostics/preflight-*.json
diagnostics/swarm-baseline-*.stdout.log
diagnostics/swarm-baseline-*.stderr.log
diagnostics/swarm-launch-baseline-*.json
diagnostics/backend-baseline-*.json
```

If the override was required, include the matching `gfxoverride` reports as well.

## Decision after the spike

### Passes baseline

Proceed with SwarmUI as the StableAMD base and begin simplifying Generate / Models / Gallery / Settings.

### Passes only with gfx1030 override

Proceed cautiously. StableAMD should own AMD environment setup and diagnostics rather than rely entirely on SwarmUI's default AMD detection.

### Swarm starts, but embedded PyTorch cannot use the GPU

Investigate the exact ComfyUI portable AMD / PyTorch package combination before changing the frontend.

### Windows path remains unstable

Keep the StableAMD UI direction, but evaluate a Linux/WSL2 backend or another ROCm packaging route. Do not fall back to DirectML automatically without measuring the alternatives.
