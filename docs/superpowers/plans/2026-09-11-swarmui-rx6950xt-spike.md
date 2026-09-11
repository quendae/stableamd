# SwarmUI RX 6950 XT Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable Windows validation harness that proves whether SwarmUI + ComfyUI can execute ROCm/PyTorch workloads on an RX 6950 XT before StableAMD forks or reshapes SwarmUI.

**Architecture:** Keep SwarmUI external and pinned under `.runtime/SwarmUI`. Add a PowerShell preflight, an upstream bootstrapper, and an embedded-Python GPU smoke test. Record diagnostics locally and treat `HSA_OVERRIDE_GFX_VERSION=10.3.0` as an explicit second test mode rather than a hidden default.

**Tech Stack:** PowerShell 7/Windows PowerShell 5.1 compatible syntax, Pester 5 for unit tests, SwarmUI 0.9.8-Beta, ComfyUI portable AMD backend, embedded PyTorch/ROCm.

**Spec:** `docs/superpowers/specs/2026-09-11-swarmui-rx6950xt-spike-design.md`

## Global Constraints

- Target machine: Windows 11 with Radeon RX 6950 XT 16 GB (`gfx1030`).
- Windows ROCm support for RX 6950 XT is experimental, not guaranteed.
- Do not install or change AMD display drivers.
- Do not silently enable `HSA_OVERRIDE_GFX_VERSION`.
- Keep downloaded runtimes and diagnostics out of git.
- Do not fork/modify SwarmUI UI until the GPU backend smoke test passes.

---

### Task 1: Hardware classification module

**Files:**
- Create: `tests/StableAmd.Hardware.Tests.ps1`
- Create: `scripts/StableAmd.Hardware.psm1`

**Interfaces:**
- Produces: `Resolve-StableAmdGfxTarget -Name <string>` -> string/null
- Produces: `Get-StableAmdSupportTier -Name <string>` -> PSCustomObject

- [ ] **Step 1: Write failing Pester tests** covering RX 6950 XT -> `gfx1030`, case-insensitive names, and unknown GPU -> null/unknown.
- [ ] **Step 2: Run** `Invoke-Pester tests/StableAmd.Hardware.Tests.ps1` and confirm failure because the module/functions do not exist.
- [ ] **Step 3: Implement the minimal module** with only the mappings required by this spike.
- [ ] **Step 4: Re-run Pester** and confirm all tests pass.
- [ ] **Step 5: Commit** the tests and module.

### Task 2: Windows AMD preflight

**Files:**
- Create: `scripts/Test-AmdPreflight.ps1`

**Interfaces:**
- Consumes: `Resolve-StableAmdGfxTarget`, `Get-StableAmdSupportTier`
- Produces: `diagnostics/preflight-<timestamp>.json`

- [ ] **Step 1: Add behavior tests** for report-shape construction to the Pester suite using injected controller data.
- [ ] **Step 2: Run Pester** and confirm the new test fails.
- [ ] **Step 3: Implement report construction** and the Windows command/CIM collection wrapper.
- [ ] **Step 4: Run Pester** and a syntax check on Windows PowerShell/PowerShell 7.
- [ ] **Step 5: Commit** the preflight script.

### Task 3: SwarmUI pinned bootstrap

**Files:**
- Create: `scripts/Install-SwarmSpike.ps1`
- Create: `.gitignore`

**Interfaces:**
- Consumes: local Git, upstream `mcmonkeyprojects/SwarmUI`
- Produces: `.runtime/SwarmUI`
- Modes: `Baseline`, `GfxOverride`

- [ ] **Step 1: Add tests** for mode-to-environment behavior (`Baseline` clears spike override; `GfxOverride` sets `10.3.0`).
- [ ] **Step 2: Run Pester** and confirm failure.
- [ ] **Step 3: Implement clone/pin/launch logic** with default ref `0.9.8-Beta` and `--launch_mode none`.
- [ ] **Step 4: Verify** the script refuses non-Windows use and missing Git with actionable errors.
- [ ] **Step 5: Commit** bootstrap and ignore rules.

### Task 4: Embedded ComfyUI GPU smoke test

**Files:**
- Create: `scripts/Test-SwarmBackend.ps1`

**Interfaces:**
- Consumes: `.runtime/SwarmUI/dlbackend/comfy/python_embeded/python.exe`
- Produces: `diagnostics/backend-<timestamp>.json`

- [ ] **Step 1: Define expected probe JSON fields** in tests/documentation.
- [ ] **Step 2: Implement the probe** using embedded Python: torch version, HIP version, availability, device name, VRAM, FP16 matrix multiply, synchronize, elapsed time.
- [ ] **Step 3: Ensure** missing backend returns a clear instruction to finish SwarmUI AMD installation first.
- [ ] **Step 4: Verify** JSON parse handling and non-zero Python exits are preserved in diagnostics.
- [ ] **Step 5: Commit** backend smoke test.

### Task 5: Operator runbook and corrected support statement

**Files:**
- Create: `docs/RX6950XT-SWARMUI-SPIKE.md`
- Modify: `README.md`

**Interfaces:**
- Produces: exact user workflow for baseline -> backend install -> tensor test -> optional gfx override -> manual SDXL generation.

- [ ] **Step 1: Document baseline commands** and expected pass/fail signals.
- [ ] **Step 2: Document the override retry** only after baseline failure.
- [ ] **Step 3: Correct README wording** so RX 6950 XT Windows ROCm is described as experimental rather than officially supported/release-ready.
- [ ] **Step 4: Add the exact diagnostics files to share after testing.**
- [ ] **Step 5: Commit** documentation updates.

### Task 6: Verification gate

- [ ] Run Pester tests on Windows.
- [ ] Run `Test-AmdPreflight.ps1` on the RX 6950 XT host.
- [ ] Run SwarmUI baseline bootstrap and finish AMD/ComfyUI install.
- [ ] Run `Test-SwarmBackend.ps1` baseline.
- [ ] If baseline fails, rerun SwarmUI and backend test with `GfxOverride` and compare reports.
- [ ] Generate one SDXL 1024x1024 image manually in SwarmUI.
- [ ] Decide whether to proceed with SwarmUI fork/simplification based on measured results.
