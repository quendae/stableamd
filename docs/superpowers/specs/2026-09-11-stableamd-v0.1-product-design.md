# StableAMD v0.1 Product Design

## Status
Approved for implementation on 2026-09-11 after the RX 6950 XT Windows feasibility spike proved native SDXL generation through TheRock ROCm, PyTorch and ComfyUI.

## Product goal
StableAMD v0.1 turns the successful feasibility stack into a usable Windows-first local image generation product for AMD Radeon users. The first supported target is AMD Radeon RX 6950 XT (`gfx1030`, 16 GiB), but the runtime architecture must keep GPU targeting data-driven so later Radeon devices can be added without redesigning the application.

StableAMD owns installation, runtime lifecycle, model management, generation presets, diagnostics and the user-facing UI. ComfyUI remains an internal inference engine and its node graph is not exposed in the normal product flow.

## Proven foundation
The spike established the following working path on Windows:

`RX 6950 XT -> TheRock multi-arch nightly -> PyTorch ROCm -> ComfyUI -> SDXL 1024x1024`

The validated test used `torch 2.13.0+rocm10.1.0a20260822`, `device-gfx1030`, ComfyUI 0.35.0 and the official SDXL 1.0 base checkpoint. A 1024x1024, 20-step SDXL image completed successfully in about 102 seconds with approximately 14 GiB peak VRAM usage.

SwarmUI was useful as a bootstrap and model source during the spike, but StableAMD v0.1 will not depend on the SwarmUI user interface. Existing SwarmUI model folders may be reused when present.

## User experience
The normal user flow is intentionally small:

1. Start StableAMD.
2. StableAMD detects the supported AMD GPU and verifies/starts the managed ComfyUI backend.
3. The Generate page offers prompt, model, size, steps, CFG, seed and a small Advanced section.
4. The Models page lists installed checkpoints and can import a local `.safetensors` file or download a Hugging Face model.
5. Generated images appear in Gallery with metadata and a reuse-settings action.
6. Settings and Diagnostics expose GPU/runtime information without requiring the user to open ComfyUI.

The user should not need to edit environment variables, Python paths, ComfyUI workflows or model directory structures for normal use.

## Architecture

### 1. Managed runtime
StableAMD manages one local ComfyUI process backed by the tested TheRock Python environment.

Responsibilities:
- resolve the StableAMD runtime directory and paths;
- verify the embedded TheRock Python and isolated ComfyUI checkout;
- create the ComfyUI extra-model-path configuration;
- start ComfyUI on a configured localhost port;
- poll `/system_stats` until healthy;
- persist PID, URL, logs and device metadata;
- report running/stopped/degraded state;
- stop only the process recorded in StableAMD state.

The runtime state is ephemeral and lives under `.runtime/stableamd/`. It is not committed.

### 2. Model library
StableAMD maintains a lightweight model registry. The registry describes files; it does not duplicate multi-gigabyte checkpoints unnecessarily.

Initial model operations:
- discover existing `.safetensors` checkpoints under configured model roots;
- validate safetensors structure before registration;
- import a local checkpoint by copy or move into the StableAMD model root;
- download a Hugging Face file with resumable transfer support;
- optionally verify a provided SHA-256;
- list and remove registry entries.

The official SDXL base model is the reference compatibility model for v0.1.

### 3. Generation service
StableAMD builds API-format ComfyUI workflows internally. v0.1 supports SDXL txt2img only.

Inputs:
- prompt;
- negative prompt;
- checkpoint;
- width and height;
- steps;
- CFG;
- seed;
- sampler;
- scheduler.

The service submits to `/prompt`, polls `/history/{prompt_id}`, fails immediately on execution errors, and records the produced image plus generation metadata.

Default v0.1 preset:
- 1024x1024;
- 20 steps;
- CFG 7.0;
- Euler sampler;
- normal scheduler;
- batch size 1.

### 4. Local application API and UI
The first UI will be a small local web application. It will call a thin StableAMD application API rather than talking directly to arbitrary ComfyUI nodes.

Initial pages:
- Generate;
- Models;
- Gallery;
- Settings;
- Diagnostics.

The backend API will expose stable product-level concepts such as runtime status, model list and txt2img generation. Raw ComfyUI workflow editing is explicitly out of scope for v0.1.

## Repository layout

```text
stableamd/
  app/
    backend/
    frontend/
  config/
    stableamd.default.json
  docs/
    superpowers/
      specs/
      plans/
  scripts/
    StableAmd.Hardware.psm1
    StableAmd.Runtime.psm1
    StableAmd.Models.psm1
    Start-StableAMD.ps1
    Stop-StableAMD.ps1
    Get-StableAMDStatus.ps1
    Install-Model.ps1
    List-Models.ps1
    Validate-Model.ps1
    Invoke-Txt2Img.ps1
    probes/
  tests/
  .runtime/        # ignored
  diagnostics/     # ignored
```

## Configuration contract
StableAMD ships `config/stableamd.default.json` as version-controlled defaults. Runtime-local overrides are stored at `.runtime/stableamd/config.json`.

Initial schema:

```json
{
  "schemaVersion": 1,
  "backend": {
    "host": "127.0.0.1",
    "port": 8190,
    "startupTimeoutSeconds": 240
  },
  "generation": {
    "outputDirectory": ".runtime/stableamd/output",
    "defaultWidth": 1024,
    "defaultHeight": 1024,
    "defaultSteps": 20,
    "defaultCfg": 7.0,
    "defaultSampler": "euler",
    "defaultScheduler": "normal"
  },
  "models": {
    "roots": [
      ".runtime/stableamd/models/checkpoints",
      ".runtime/SwarmUI/Models/Stable-Diffusion"
    ]
  }
}
```

Paths in configuration are repository-relative unless absolute.

## Runtime state contract
`.runtime/stableamd/backend-state.json` records the last managed backend session:

```json
{
  "schemaVersion": 1,
  "pid": 12345,
  "url": "http://127.0.0.1:8190/",
  "startedAtUtc": "2026-09-11T16:00:00Z",
  "pythonPath": ".../python.exe",
  "comfyRoot": ".../ComfyUI",
  "stdoutLog": ".../backend.stdout.log",
  "stderrLog": ".../backend.stderr.log",
  "device": {
    "name": "cuda:0 AMD Radeon RX 6950 XT : native",
    "type": "cuda",
    "vramTotal": 17163091968
  }
}
```

A stale PID must never be trusted without checking that the process still exists and the configured HTTP health endpoint answers.

## Model registry contract
`.runtime/stableamd/models.json` is generated state and is not committed.

Each entry contains:
- stable id;
- display name;
- absolute path;
- model family when known (`sdxl`, `sd15`, `unknown`);
- byte size;
- SHA-256 when known;
- safetensors validation status;
- source metadata (`local`, `huggingface`, `discovered`).

Registry entries never replace on-disk validation. A generation request must still verify that the selected path exists.

## Error handling
StableAMD should fail early with product-level messages. Important cases:
- unsupported/missing GPU;
- missing TheRock runtime;
- incomplete ComfyUI checkout;
- backend port already in use;
- stale runtime state;
- corrupt safetensors file;
- ComfyUI execution error;
- download/hash mismatch.

Diagnostics retain raw logs and machine-readable JSON reports where useful.

## Security and networking
v0.1 binds all local services to `127.0.0.1` only. No remote access, authentication, telemetry or cloud upload is introduced in v0.1.

## v0.1 acceptance criteria
StableAMD v0.1 is complete when a clean supported Windows machine can:
- detect RX 6950 XT / `gfx1030`;
- install or reuse the tested TheRock runtime;
- start, query and stop the managed ComfyUI backend;
- list/import/download and validate a checkpoint;
- generate an SDXL txt2img image through StableAMD without opening ComfyUI;
- show generated images and metadata in a simple local UI;
- show actionable runtime and model diagnostics.

## Explicitly deferred
The following are not required for v0.1:
- raw ComfyUI node editor;
- LoRA management;
- ControlNet;
- inpainting;
- Flux support;
- video generation;
- remote/LAN access;
- WSL2 as the primary backend;
- DirectML or ZLUDA as the primary backend.
