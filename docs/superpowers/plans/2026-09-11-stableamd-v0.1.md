# StableAMD v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the proven RX 6950 XT Windows TheRock/ComfyUI spike into a usable StableAMD v0.1 with managed runtime lifecycle, model management, SDXL txt2img generation, and a simple local web UI.

**Architecture:** StableAMD owns product-level state and lifecycle while ComfyUI remains an internal inference engine. PowerShell modules/scripts provide the Windows runtime, model and generation service contracts first; a small local application layer and frontend are then built on top of those stable contracts. Runtime state and downloaded/generated assets live under `.runtime/stableamd/` and are not committed.

**Tech Stack:** Windows PowerShell 5.1-compatible scripts, Pester 5 tests, Python helper probes where binary/model parsing is easier, TheRock multi-arch ROCm nightly, PyTorch ROCm, ComfyUI HTTP API, local HTML/CSS/JavaScript UI in the first release.

**Spec:** `docs/superpowers/specs/2026-09-11-stableamd-v0.1-product-design.md`

## Global Constraints

- Windows is the primary platform for v0.1.
- RX 6950 XT / `gfx1030` is the first validated target.
- TheRock + PyTorch ROCm + ComfyUI is the primary inference path.
- Bind local services to `127.0.0.1` only.
- Do not expose the ComfyUI node graph in the normal UI.
- Do not copy multi-gigabyte checkpoints unless an explicit import operation requires it.
- Keep `.runtime/` and `diagnostics/` out of git.
- Use TDD for behavior changes and keep PowerShell 5.1 compatibility.
- SDXL txt2img is the only required generation family for v0.1.

---

### Task 1: Runtime configuration and path contract

**Files:**
- Create: `config/stableamd.default.json`
- Create: `scripts/StableAmd.Runtime.psm1`
- Create: `tests/StableAmd.Runtime.Tests.ps1`

**Interfaces:**
- Produces: `New-StableAmdDefaultConfig`, `Resolve-StableAmdPath`, `Get-StableAmdRuntimePaths`, `Read-StableAmdConfig`, `Write-StableAmdBackendState`, `Read-StableAmdBackendState`.
- Later runtime scripts consume these functions.

- [ ] **Step 1: Write failing Pester tests** for default values, repository-relative path resolution, absolute-path pass-through, and backend state round-trip.
- [ ] **Step 2: Run CI and verify RED** because `StableAmd.Runtime.psm1` does not exist.
- [ ] **Step 3: Implement minimal runtime module and default JSON.**
- [ ] **Step 4: Run CI and verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 2: Managed backend start/status/stop

**Files:**
- Create: `scripts/Start-StableAMD.ps1`
- Create: `scripts/Get-StableAMDStatus.ps1`
- Create: `scripts/Stop-StableAMD.ps1`
- Modify: `tests/StableAmd.Runtime.Tests.ps1`

**Interfaces:**
- `Start-StableAMD.ps1` returns a state/status object and writes `.runtime/stableamd/backend-state.json`.
- `Get-StableAMDStatus.ps1` returns `running`, `stopped`, or `degraded` plus health/device details.
- `Stop-StableAMD.ps1` stops only the PID recorded by StableAMD and clears active state.

- [ ] **Step 1: Add failing contract tests** for isolation, loopback binding, state path use, `/system_stats` healthcheck, and safe stop behavior.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement start/status/stop using the already-proven `run_comfy_isolated.py` launcher and TheRock runtime.**
- [ ] **Step 4: Verify GREEN in CI and manually on the RX 6950 XT.**
- [ ] **Step 5: Commit.**

### Task 3: Model registry and discovery

**Files:**
- Create: `scripts/StableAmd.Models.psm1`
- Create: `scripts/List-Models.ps1`
- Create: `scripts/Validate-Model.ps1`
- Create: `tests/StableAmd.Models.Tests.ps1`

**Interfaces:**
- Produces: `Get-StableAmdModelId`, `Get-StableAmdModelFamily`, `Read-StableAmdModelRegistry`, `Write-StableAmdModelRegistry`, `Find-StableAmdCheckpoints`.
- Reuses `scripts/probes/validate_safetensors.py` for structural validation.

- [ ] **Step 1: Add failing tests** for stable model ids, `.safetensors` discovery, SDXL family inference and registry round-trip.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement registry/discovery/validation.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 4: Local and Hugging Face model installation

**Files:**
- Create: `scripts/Install-Model.ps1`
- Modify: `scripts/StableAmd.Models.psm1`
- Modify: `tests/StableAmd.Models.Tests.ps1`

**Interfaces:**
- Local mode consumes a file path and imports it into the StableAMD checkpoint root.
- Hugging Face mode consumes repository id + filename or a resolved HTTPS URL, supports resume, optional SHA-256, and validates the final safetensors structure before registry update.

- [ ] **Step 1: Add failing tests** for destination naming, collision handling, SHA-256 comparison and source metadata.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement local import and resumable HTTP/Hugging Face download path.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 5: Reusable SDXL txt2img service

**Files:**
- Create: `scripts/StableAmd.Generation.psm1`
- Create: `scripts/Invoke-Txt2Img.ps1`
- Create: `tests/StableAmd.Generation.Tests.ps1`
- Refactor: `scripts/Test-TheRockSdxl.ps1` only where helpers can be reused without weakening the spike test.

**Interfaces:**
- Produces `New-StableAmdSdxlWorkflow` and generation request/result objects.
- Uses the managed backend URL from runtime status and a model selected from the registry.

- [ ] **Step 1: Add failing tests** for workflow JSON, defaults, custom seed/size/CFG/steps and output metadata.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement workflow builder and API submission/history polling.**
- [ ] **Step 4: Verify GREEN in CI and perform one real RX 6950 XT generation.**
- [ ] **Step 5: Commit.**

### Task 6: Generation history and gallery metadata

**Files:**
- Create: `scripts/Get-GenerationHistory.ps1`
- Modify: `scripts/StableAmd.Generation.psm1`
- Modify: `tests/StableAmd.Generation.Tests.ps1`

**Interfaces:**
- Each successful generation writes a sidecar JSON record under `.runtime/stableamd/history/`.
- History returns newest-first records with image path, prompt, model, dimensions, seed, timing and settings.

- [ ] **Step 1: Add failing history serialization/sort tests.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement sidecar persistence and history listing.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 7: Local application API

**Files:**
- Create: `app/backend/stableamd_server.py`
- Create: `tests/test_stableamd_server.py`
- Modify: `.github/workflows/powershell-tests.yml` or add a dedicated Python test workflow if needed.

**Interfaces:**
- Loopback-only HTTP API for runtime status, models, generation, history and diagnostics.
- API invokes StableAMD service contracts rather than allowing arbitrary commands/workflows.

- [ ] **Step 1: Add failing Python API tests.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement minimal loopback API.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit.**

### Task 8: Local web UI shell

**Files:**
- Create: `app/frontend/index.html`
- Create: `app/frontend/app.js`
- Create: `app/frontend/styles.css`
- Create: `tests/frontend-smoke.ps1` or equivalent static contract test.

**Interfaces:**
- Pages/tabs: Generate, Models, Gallery, Settings, Diagnostics.
- Frontend talks only to the StableAMD local application API.

- [ ] **Step 1: Add failing static/UI contract tests.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement responsive UI shell and Generate flow first, then the remaining pages.**
- [ ] **Step 4: Verify GREEN and manual desktop browser smoke test.**
- [ ] **Step 5: Commit.**

### Task 9: One-click product launcher

**Files:**
- Create: `Start-StableAMD.cmd`
- Create: `scripts/Launch-StableAMD.ps1`
- Modify: `README.md`
- Modify: tests as needed.

**Interfaces:**
- One command starts/repairs required runtime components, starts the managed backend and local application server, then opens the browser UI.

- [ ] **Step 1: Add failing launcher contract tests.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement launcher orchestration.**
- [ ] **Step 4: Verify GREEN and perform clean-start manual test.**
- [ ] **Step 5: Commit.**

### Task 10: Packaging and v0.1 acceptance pass

**Files:**
- Create or modify release packaging scripts under `scripts/`.
- Modify: `README.md`
- Create: `docs/v0.1-validation.md`

**Interfaces:**
- Produces a reproducible user-facing package/installer flow without committing `.runtime` binaries or models.

- [ ] **Step 1: Document acceptance checklist from the spec.**
- [ ] **Step 2: Run all CI tests.**
- [ ] **Step 3: Run runtime start/status/stop on RX 6950 XT.**
- [ ] **Step 4: Import/list/validate an SDXL checkpoint and perform txt2img generation.**
- [ ] **Step 5: Smoke-test all UI pages and diagnostics.**
- [ ] **Step 6: Record exact TheRock/PyTorch/ComfyUI versions proven for v0.1.**
- [ ] **Step 7: Commit release documentation.**
