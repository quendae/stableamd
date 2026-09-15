# LoRA Compatibility and Post-Generation Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LoRA selection model-family aware, then add first-class gallery actions for upscale, img2img, inpaint and outpaint before starting Krea2.

**Architecture:** StableAMD will build a conservative LoRA catalog from safetensors metadata, managed-family folders and filename hints, and will enforce known incompatibilities in both UI and backend while allowing unknown adapters with a warning. Gallery actions will reuse existing generated images through local `/api/image` fetches. Upscaling will start with stock ComfyUI `UpscaleModelLoader -> ImageUpscaleWithModel -> SaveImage` so common ESRGAN-family models work without custom nodes; SeedVR2 is an optional later provider because it requires a custom node stack and materially higher VRAM.

**Tech Stack:** Windows PowerShell 5.1/7, Python 3.12, ComfyUI 0.35 pinned runtime, vanilla JS frontend, Pester + unittest.

**Spec:** Current v0.3 model-family LoRA layout, SDXL img2img/inpaint implementation, and user-approved post-generation workflow from the 2026-09-13 StableAMD conversation.

## Global Constraints

- Keep `feat/stableamd-v0.3` as the implementation branch; do not merge PR #4 yet.
- Preserve existing SDXL/Z-Image generation and the proven gfx1030 memory profile.
- Unknown LoRA compatibility must not be guessed as compatible; mark it unknown and warn.
- Known cross-family LoRA combinations must be blocked server-side, not only hidden in the UI.
- Keep classic model-based upscale independent from diffusion-model family.
- SeedVR2 remains optional/experimental until a separate runtime/dependency and RX 6950 XT acceptance test is complete.
- All generated/upscaled/edited outputs remain local and appear in StableAMD history/gallery.

---

### Task 1: LoRA metadata catalog and compatibility enforcement

**Files:**
- Create: `app/backend/lora_catalog.py`
- Modify: `app/backend/stableamd_v03_server.py`
- Modify: `app/frontend/app-v02.js`
- Test: `tests/test_v03_lora_catalog.py`
- Test: `tests/StableAmd.V03.LoraCompatibility.Tests.ps1`

**Interfaces:**
- Produces: `scan_lora_catalog(roots) -> list[dict]`, each entry with `name`, `path`, `family`, `confidence`, `reason`.
- Produces API: `GET /api/lora-catalog`.
- Backend generation validation rejects `known incompatible` LoRAs for the selected model family; `unknown` remains allowed with metadata/warning.

- [ ] **Step 1: Write RED tests** covering SDXL/Z-Image/Flux family inference from `__metadata__`, managed folder inference, filename fallback, unknown classification, and backend/UI contract strings.
- [ ] **Step 2: Run CI and verify only the new tests fail.**
- [ ] **Step 3: Implement safetensors-header parsing without loading tensor payloads.** Read the first 8 little-endian bytes as header length, parse header JSON, inspect `__metadata__`, and conservatively map values such as `sdxl_base_v1-0`, `sd_v1-5`, `flux`, `sd3`, `z-image`, `krea`.
- [ ] **Step 4: Add folder and filename fallback.** Managed family folder has higher confidence than filename; unclassified external files remain `unknown`.
- [ ] **Step 5: Add `/api/lora-catalog` and generation validation.** Reject a selected LoRA when both model and LoRA families are known and differ; do not reject `shared` or `unknown`.
- [ ] **Step 6: Update LoRA/MultiLoRA UI.** Show compatibility labels, hide incompatible adapters by default, offer `Show incompatible`, and clear/disable stale incompatible stack entries after model switch.
- [ ] **Step 7: Run full CI and commit.**

### Task 2: Gallery handoff actions

**Files:**
- Modify: `app/frontend/app.js`
- Modify: `app/frontend/app-v02.js`
- Modify: `app/frontend/app-inpaint.js`
- Modify: `app/frontend/styles.css`
- Test: `tests/StableAmd.V03.PostGeneration.Tests.ps1`

**Interfaces:**
- Produces gallery actions: `Upscale`, `Img2Img`, `Inpaint`, `Outpaint`.
- Produces browser event: `stableamd:load-generated-image` with `{ imagePath, action, record }`.

- [ ] **Step 1: Write RED frontend contract tests** for the four actions and generated-image handoff event.
- [ ] **Step 2: Add action buttons to every gallery item with an image.**
- [ ] **Step 3: Implement `Img2Img` handoff.** Fetch `/api/image`, create a local `File`, populate the existing img2img file input via `DataTransfer`, switch to Generate and `img2img`.
- [ ] **Step 4: Implement `Inpaint` handoff.** Add a public inpaint loader that accepts a Blob/File and preloads the existing editor, then switch generation mode to `inpaint`.
- [ ] **Step 5: Implement `Outpaint` handoff shell.** Load the image into the same editor and reveal expansion controls for left/right/top/bottom; added canvas areas become the initial mask.
- [ ] **Step 6: Run full CI and commit.**

### Task 3: Stock ComfyUI upscale provider

**Files:**
- Create: `scripts/StableAmd.Upscale.psm1`
- Create: `scripts/List-UpscaleModels.ps1`
- Modify: `scripts/StableAmd.Runtime.psm1`
- Modify: `scripts/Start-StableAMD.ps1`
- Modify: `app/backend/stableamd_v03_server.py`
- Create: `app/frontend/app-upscale.js`
- Modify: `app/frontend/index.html`
- Test: `tests/StableAmd.V03.Upscale.Tests.ps1`
- Test: `tests/test_v03_upscale_api.py`

**Interfaces:**
- Managed root: `.runtime/stableamd/models/upscale_models` exposed to ComfyUI as `upscale_models`.
- API: `GET /api/upscale-models`, `POST /api/upscale` with `{ imagePath, modelName, outputScale? }`.
- Workflow: `LoadImage -> UpscaleModelLoader -> ImageUpscaleWithModel -> optional ImageScale -> SaveImage`.

- [ ] **Step 1: Write RED workflow/API/root tests.**
- [ ] **Step 2: Add managed upscale-model root and ComfyUI extra path.**
- [ ] **Step 3: Implement model discovery from ComfyUI `UpscaleModelLoader` choices.**
- [ ] **Step 4: Implement stock upscale workflow and output/history correlation.**
- [ ] **Step 5: Add modal/panel launched by Gallery `Upscale`, with model selector and native/model scale information.**
- [ ] **Step 6: Add recommended optional-download catalog entries only for models with stable public sources: RealESRGAN x2/x4 and 4x-UltraSharp; installation must be explicit user action.**
- [ ] **Step 7: Run full CI and target-machine acceptance on RX 6950 XT.**

### Task 4: Outpaint completion and SeedVR2 experimental provider

**Files:**
- Modify: `app/frontend/app-inpaint.js`
- Modify: `app/backend/stableamd_v03_server.py`
- Create: `config/upscale-providers.v0.3.json`
- Add SeedVR2 provider files only after dependency/runtime probe succeeds.
- Test: dedicated Pester/Python tests for outpaint geometry and optional provider gating.

**Interfaces:**
- Outpaint reuses SDXL inpainting with an expanded transparent PNG and explicit border mask.
- SeedVR2 is advertised only if the custom node classes and required model assets are detected.

- [ ] **Step 1: Add outpaint geometry tests** for asymmetric left/right/top/bottom expansion and mask initialization.
- [ ] **Step 2: Implement expanded-canvas source generation and send it through existing SDXL inpaint API.**
- [ ] **Step 3: Add SeedVR2 capability probe.** Require custom node presence and model asset discovery before showing the provider.
- [ ] **Step 4: Benchmark SeedVR2 3B reduced-memory mode on RX 6950 XT before marking it usable.** If it cannot run reliably in 16 GiB, keep it unavailable with a clear VRAM requirement instead of degrading StableAMD defaults.
- [ ] **Step 5: Run full CI and update PR status notes.**
