# Character Sheet v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace StableAMD's heuristic sequential Character Sheet with a training-matched Krea 2 Identity Edit v1.2 workflow that preserves the actual person/character, performs local panel extraction and face/detail cleanup, and persists one clean final sheet.

**Architecture:** Add a dedicated Krea Identity Edit provider layer next to the accepted Ostris edit path, then route `editTask="character-sheet"` to a v2 orchestrator when its pinned dependencies are ready. v2 generates one 1792x1024 five-panel sheet through `Krea2EditModelPatch` + `Krea2EditGroundedEncode`, locally extracts panels, optionally detail-refines detected face/head regions against the original identity crop, stitches them back, and persists one final composite; the existing sequential implementation remains available as `legacy-sequential` during acceptance.

**Tech Stack:** Python 3, ComfyUI graph JSON, Krea 2 Turbo FP8, `lbouaraba/comfyui-krea2edit`, Krea 2 Identity Edit v1.2 LoRA, Pillow, existing DWPose runtime, vanilla JS frontend, PowerShell/Pester packaging tests, Python unittest regression suite.

**Spec:** `docs/superpowers/specs/2026-09-21-character-sheet-v2-design.md`

## Global Constraints

- Physical target remains Windows + Radeon RX 6950 XT 16 GiB (`gfx1030`).
- Keep existing accepted Krea txt2img, normal Image Edit/Ostris, OpenPose, Depth, Z-Image, Gallery and user-LoRA routes unchanged unless a task explicitly says otherwise.
- v2 base output is exactly `1792x1024` (1.84 MP, divisible by 16, below the documented ~2 MP Identity Edit ceiling).
- Identity LoRA is `krea2_identity_edit_v1_2.safetensors` at model strength `1.0`.
- Krea Identity Edit v1.2 settings are server-owned for acceptance: `fit_mode="fit"`, `ref_boost=4.0`, `grounding_px=1024`, `10 steps`, `CFG=1`, `Euler`, `simple`, `denoise=1`.
- `target_latent` must be wired to `Krea2EditModelPatch` whenever the pixel path is used.
- No parallel Krea jobs in v2; call ComfyUI `/free` after the base job and after every detailer job.
- Missing v2 dependency must be actionable and must not silently present legacy output as v2.
- Detailer failure is non-fatal; base panel survives and records `detailerSkipped=true`.
- Only after the final composite/history is persisted successfully are base/detailer intermediates hidden from default Gallery.

## Review Focus

- Source image with a very different aspect ratio from `1792x1024`: v1.2 `fit` geometry must be used instead of center-cropping identity away.
- Missing/corrupt Identity Edit LoRA or node pack: v2 must be unavailable with an install/restart message, never an opaque ComfyUI node error.
- DWPose cannot find a usable face in one generated panel: the panel must remain unchanged and the rest of the sheet must continue.
- BACK panel accidentally yields a face detection: BACK must never run face refinement.
- A detailer job crashes after the base sheet exists: final compose must use the base panel, retain diagnostic metadata, and still finish if the remaining stages are healthy.

---

### Task 1: Pin and expose the Krea Identity Edit dependency

**Files:**
- Create: `app/backend/stableamd_v03_krea_identity_edit.py`
- Modify: `app/backend/stableamd_v03_edit_server.py`
- Test: `tests/test_v03_krea_identity_edit.py`

**Interfaces:**
- Consumes: existing `ControlNetBridgeMixin._node_available()`, `_lora_choice_by_leaf()`, `_comfy_json()`, repo runtime paths, and the safe download/install patterns in `stableamd_v03_controlnet.py`.
- Produces: `KreaIdentityEditBridgeMixin`, `KreaIdentityEditApiMixin`, `krea_identity_dependency() -> dict`, `install_krea_identity_dependency() -> dict`, `_krea_identity_edit_ready() -> bool`, and pinned public constants used by later tests/tasks.

- [ ] **Step 1: Write the failing dependency/readiness tests**

Create `tests/test_v03_krea_identity_edit.py` with tests equivalent to:

```python
class KreaIdentityDependencyTests(unittest.TestCase):
    def test_dependency_requires_both_nodes_and_identity_lora(self):
        class Parent:
            repo_root = Path(".")
            def _node_available(self, name):
                return name in {"Krea2EditModelPatch", "Krea2EditGroundedEncode", "LoraLoaderModelOnly"}
            def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
                return f"krea/{filename}" if filename == identity.KREA_IDENTITY_LORA_FILENAME else None
        class Bridge(identity.KreaIdentityEditBridgeMixin, Parent):
            pass
        self.assertTrue(Bridge()._krea_identity_edit_ready())

    def test_dependency_metadata_is_pinned_and_installable(self):
        dep = identity.KreaIdentityEditBridgeMixin._dependency_descriptor_static()
        self.assertEqual(dep["id"], "krea2-identity-edit-v1.2")
        self.assertEqual(dep["plugin"]["commit"], identity.KREA_IDENTITY_PLUGIN_COMMIT)
        self.assertEqual(dep["model"]["filename"], "krea2_identity_edit_v1_2.safetensors")
        self.assertRegex(dep["model"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(dep["model"]["sizeBytes"], 1_000_000_000)
```

Also add an API test that `GET /api/krea-identity/dependency` returns the descriptor and `POST /api/krea-identity/install` accepts only `{}` or the expected dependency id.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m unittest tests.test_v03_krea_identity_edit -v
```

Expected: import/module failure because `stableamd_v03_krea_identity_edit.py` does not exist yet.

- [ ] **Step 3: Implement pinned dependency constants and readiness**

Create `stableamd_v03_krea_identity_edit.py` with these fixed identities:

```python
KREA_IDENTITY_DEPENDENCY_ID = "krea2-identity-edit-v1.2"
KREA_IDENTITY_PLUGIN_REPOSITORY = "https://github.com/lbouaraba/comfyui-krea2edit.git"
KREA_IDENTITY_PLUGIN_COMMIT = "86f886dac23013d88996e3a2e99093ba44d322fb"
KREA_IDENTITY_PLUGIN_LICENSE = "Apache-2.0"
KREA_IDENTITY_LORA_REPOSITORY = "conradlocke/krea2-identity-edit"
KREA_IDENTITY_LORA_REVISION = "main"
KREA_IDENTITY_LORA_FILENAME = "krea2_identity_edit_v1_2.safetensors"
KREA_IDENTITY_LORA_LICENSE = "Krea 2 Community License"
KREA_IDENTITY_REQUIRED_NODES = ("Krea2EditModelPatch", "Krea2EditGroundedEncode", "LoraLoaderModelOnly")
```

Before committing the installer constants, fetch the published v1.2 file once, compute `Get-FileHash -Algorithm SHA256`, record its exact byte length, and hard-code both as `KREA_IDENTITY_LORA_BYTES` and `KREA_IDENTITY_LORA_SHA256`. The installer must reject any existing/downloaded file whose length or SHA256 differs.

Implement `_krea_identity_edit_ready()` as all required nodes available plus exactly one ComfyUI LoRA choice matching the pinned filename.

- [ ] **Step 4: Implement managed installation and API**

Reuse the control dependency install safety contract, but keep a dedicated endpoint:

```text
GET  /api/krea-identity/dependency
POST /api/krea-identity/install
```

The plugin checkout target is:

```text
.runtime/therock-comfy/ComfyUI/custom_nodes/comfyui-krea2edit
```

The LoRA target is:

```text
.runtime/stableamd/models/loras/krea/krea2_identity_edit_v1_2.safetensors
```

Installation rules:
- clone to a UUID temporary directory;
- checkout detached exact commit;
- atomically rename only after successful checkout;
- refuse to overwrite a non-Git directory or a Git checkout at another revision;
- download to a UUID `.partial-*` file;
- enforce allow-listed Hugging Face HTTPS URL, exact byte length and SHA256;
- atomically promote only after validation;
- return `restartRequired=true` when plugin/model changed or nodes are not yet visible.

Wire `KreaIdentityEditApiMixin` into `StableAmdApi` and `KreaIdentityEditBridgeMixin` into the bridge MRO without changing non-v2 request behavior.

- [ ] **Step 5: Run dependency tests**

```powershell
python -m unittest tests.test_v03_krea_identity_edit -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/backend/stableamd_v03_krea_identity_edit.py app/backend/stableamd_v03_edit_server.py tests/test_v03_krea_identity_edit.py
git commit -m "feat: add pinned Krea identity edit dependency"
```

---

### Task 2: Build the training-matched Identity Edit ComfyUI graph

**Files:**
- Modify: `app/backend/stableamd_v03_krea_identity_edit.py`
- Test: `tests/test_v03_krea_identity_edit.py`

**Interfaces:**
- Consumes: accepted Krea base workflow from `_generate_krea2_turbo()`, `_run_script("Build-StableAmdWorkflow.ps1")`, staged input image names, and `_lora_choice_by_leaf()`.
- Produces: `_stableamd_krea_identity_context`, `_inject_krea_identity_edit(workflow, context)`, `_generate_krea_identity_edit(request, selected_model, context)` used by Task 3 and Task 4.

- [ ] **Step 1: Add failing graph-contract tests**

Construct a minimal accepted Krea workflow fixture and assert the injected graph contains, by `class_type` rather than fragile numeric ids:

```python
self.assert_node("LoraLoaderModelOnly", lora_name="krea2_identity_edit_v1_2.safetensors", strength_model=1.0)
self.assert_node("Krea2EditModelPatch", fit_mode="fit", ref_boost=4.0)
self.assert_node("Krea2EditGroundedEncode", grounding_px=1024)
self.assert_node("EmptySD3LatentImage", width=1792, height=1024)
```

Also assert:
- `VAEEncode` receives the same source image;
- `Krea2EditModelPatch.source_latent` is wired from that encode;
- `Krea2EditModelPatch.source_image` and `vae` are connected;
- `Krea2EditModelPatch.target_latent` and `KSampler.latent_image` point to the same target latent;
- sampler receives patched model and grounded positive conditioning;
- base sampler settings are `10 / 1 / euler / simple / 1`;
- no `TextEncodeKrea2OstrisEdit` node is used in this context.

- [ ] **Step 2: Run graph tests and verify RED**

```powershell
python -m unittest tests.test_v03_krea_identity_edit.KreaIdentityGraphTests -v
```

Expected: FAIL because the v1.2 graph injector is absent.

- [ ] **Step 3: Implement one-input graph injection**

Use the model author's training-matched wiring:

```text
LoadImage -> VAEEncode ----------------------> Krea2EditModelPatch.source_latent
LoadImage -----------------------------------> Krea2EditModelPatch.source_image
VAE -----------------------------------------> Krea2EditModelPatch.vae
EmptySD3LatentImage --------------------------> Krea2EditModelPatch.target_latent
UNET/base model -> Identity LoRA @1.0 --------> Krea2EditModelPatch.model
LoadImage + CLIP + prompt -> GroundedEncode --> KSampler.positive
EmptySD3LatentImage --------------------------> KSampler.latent_image
Krea2EditModelPatch --------------------------> KSampler.model
```

Set `fit_mode="fit"`, `ref_boost=4.0`, `grounding_px=1024`, width `1792`, height `1024`, steps `10`, CFG `1`, sampler `euler`, scheduler `simple`, denoise `1`.

- [ ] **Step 4: Add and implement two-input detailer context**

Extend context with optional `identity_image_name`. For two-input detailer mode:

```text
image A = generated panel/head crop to preserve camera/content
image B = original source identity crop
```

Wire A to `source_latent`/`source_image` and B to `source_latent_b`/`image_b`; the grounded encoder receives both images. Keep the same Identity LoRA and `fit` geometry. Detailer output size must be derived from the crop and aligned to 16, never exceed 1024x1024, and stay below 1 MP.

- [ ] **Step 5: Run graph tests**

```powershell
python -m unittest tests.test_v03_krea_identity_edit -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/backend/stableamd_v03_krea_identity_edit.py tests/test_v03_krea_identity_edit.py
git commit -m "feat: add Krea identity edit graph"
```

---

### Task 3: Route Character Sheet v2 through one Identity Edit base render

**Files:**
- Create: `app/backend/stableamd_v03_character_sheet_v2.py`
- Modify: `app/backend/stableamd_v03_edit_server.py`
- Test: `tests/test_v03_character_sheet_v2.py`
- Keep: `app/backend/stableamd_v03_character_sheet.py`
- Keep: `app/backend/stableamd_v03_character_sheet_anchor.py`

**Interfaces:**
- Consumes: `_krea_identity_edit_ready()`, `_generate_krea_identity_edit(...)`, legacy `compose_character_sheet()`/history helpers as references, and existing Krea model selection.
- Produces: `CharacterSheetV2BridgeMixin`, `_character_sheet_v2_prompt(description)`, `generate_character_sheet_v2(request)`, and public response metadata consumed by Task 4/5.

- [ ] **Step 1: Add failing API/routing tests**

Tests must pin:

```python
validated = api._validate_generation({
    **base_img2img_request,
    "editTask": "character-sheet",
    "characterSheetVersion": "v2",
    "characterDescription": "young girl in a red dress and bow",
    "characterSheetDetailer": True,
})
self.assertEqual(validated["characterSheetVersion"], "v2")
self.assertTrue(validated["characterSheetDetailer"])
```

Also reject unknown versions, non-string descriptions, non-boolean detailer, and legacy-only fields (`characterSheetView`, `characterSheetPhase`) when `characterSheetVersion="v2"`.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m unittest tests.test_v03_character_sheet_v2 -v
```

Expected: FAIL because v2 request fields/orchestrator do not exist.

- [ ] **Step 3: Implement v2 prompt and base render**

Default base instruction:

```text
Create one clean character sheet of the exact same person or character from the reference image on a plain neutral grey studio background. Use five clearly separated panels from left to right: (1) close-up face portrait looking toward camera, (2) full-body front view, (3) full-body three-quarter view, (4) full-body strict side profile, (5) full-body back view. Preserve exact facial identity, age impression, hair, clothing, accessories, proportions, colors and materials. Do not add props, duplicate people, inset portraits, text, borders, scenery remnants, ghost anatomy or texture debris.
```

Append:

```text
Character description: <user text>
```

only when non-empty.

The base call is one `1792x1024` Identity Edit job; no per-view v1 loop is involved.

- [ ] **Step 4: Implement routing and compatibility**

In `PowerShellBridge`, place `CharacterSheetV2BridgeMixin` before `CharacterSheetAnchorBridgeMixin` and `CharacterSheetBridgeMixin`.

Request behavior:
- `characterSheetVersion` omitted + v2 ready => v2;
- explicit `v2` + v2 missing => actionable dependency error;
- explicit `legacy-sequential` => delegate to current v1/anchor flow unchanged;
- during acceptance, if version omitted and v2 not ready => return a dependency-required error rather than silently call legacy.

- [ ] **Step 5: Assert base metadata**

Base result/history must include:

```python
{
  "CharacterSheetVersion": "v2-identity-edit",
  "CharacterSheetIdentityLora": "krea2_identity_edit_v1_2.safetensors",
  "CharacterSheetIdentityLoraStrength": 1.0,
  "CharacterSheetRefBoost": 4.0,
  "CharacterSheetGroundingPx": 1024,
  "CharacterSheetBaseImagePath": "...",
}
```

- [ ] **Step 6: Run v2 + existing character-sheet tests**

```powershell
python -m unittest tests.test_v03_character_sheet_v2 tests.test_v03_krea_character_sheet tests.test_v03_character_sheet_anchor_refine -v
```

Expected: PASS; legacy tests remain green.

- [ ] **Step 7: Commit**

```bash
git add app/backend/stableamd_v03_character_sheet_v2.py app/backend/stableamd_v03_edit_server.py tests/test_v03_character_sheet_v2.py
git commit -m "feat: add one-pass Character Sheet v2"
```

---

### Task 4: Extract panels, detail faces and feather-stitch final v2 sheet

**Files:**
- Modify: `app/backend/stableamd_v03_character_sheet_v2.py`
- Test: `tests/test_v03_character_sheet_v2.py`

**Interfaces:**
- Consumes: base `1792x1024` output, DWPose `_analyze_dwpose_candidates()`/runtime, original source image, `_generate_krea_identity_edit()` two-input mode, `/free` helper.
- Produces: `_extract_v2_panels()`, `_face_detail_box()`, `_refine_v2_panel()`, `_feather_stitch()`, `_persist_character_sheet_v2()`.

- [ ] **Step 1: Write failing deterministic image tests**

Using synthetic Pillow images, test that `_extract_v2_panels()` returns five ordered roles with no overlap/gaps beyond the intentional separators and that reassembly preserves the input width/height.

Pin BACK behavior:

```python
panels = bridge._extract_v2_panels(base_path)
self.assertEqual([p.role for p in panels], ["face", "front", "three-quarter", "side", "back"])
self.assertFalse(bridge._should_detail_panel("back"))
```

- [ ] **Step 2: Run extraction tests and verify RED**

```powershell
python -m unittest tests.test_v03_character_sheet_v2.CharacterSheetV2ImageTests -v
```

Expected: FAIL because extraction/stitch helpers are absent.

- [ ] **Step 3: Implement deterministic five-panel extraction**

Treat the generated sheet as five equal horizontal logical regions, with a small configurable edge inset (server constant, initially 1.5% of each region) so panel boundaries are not fed into the face detailer. Keep the untouched base full-sheet image as a hidden intermediate.

- [ ] **Step 4: Add failing detailer fallback tests**

Test all cases:
- face detected => one detailer call;
- no face => original panel returned with `detailerSkipped="no-face"`;
- role BACK => no DWPose/detailer call;
- detailer raises `StableAmdBridgeError` => original panel returned with `detailerSkipped="generation-failed"`;
- malformed face box => original panel retained.

- [ ] **Step 5: Implement face/head detail crop**

Use DWPose face/head bounds, expand by 45% horizontally and 65% vertically to include hair/head context, clamp to panel, and align crop output dimensions to multiples of 16. The original-source identity crop is prepared using the existing source DWPose face box; if unavailable, detailer skips rather than inventing a fallback identity.

Detailer instruction:

```text
Correct only the identity and fine facial/head details of image A so they match the same person in image B. Preserve image A's exact camera angle, head orientation, body pose, clothing, background, lighting and composition. Preserve the current strict side profile when image A is a side view. Do not add another face, portrait inset, accessories, props or background objects. Remove malformed facial texture, duplicate features, ghost details and noisy artifacts inside the edited head region.
```

- [ ] **Step 6: Implement feather stitch**

Create a soft rectangular mask with 12% feather around the crop edge and `Image.composite(refined, original, mask)` back into the original full-resolution panel. Never resize the full panel to the detailer crop size.

- [ ] **Step 7: Implement orchestration/failure semantics**

Order:

```text
base Identity Edit job
/free
extract 5 panels
FACE detail -> /free
FRONT detail -> /free
3/4 detail -> /free
SIDE detail -> /free
BACK unchanged
reassemble final sheet
persist final history
hide intermediates
```

If any detailer child fails, record skip metadata and continue. If final persistence fails, do not hide any intermediate history.

- [ ] **Step 8: Run image/orchestration tests**

```powershell
python -m unittest tests.test_v03_character_sheet_v2 -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/backend/stableamd_v03_character_sheet_v2.py tests/test_v03_character_sheet_v2.py
git commit -m "feat: detail and compose Character Sheet v2"
```

---

### Task 5: Replace sequential frontend orchestration with v2 staged UX

**Files:**
- Modify: `app/frontend/app-krea-edit.js`
- Test: `tests/test_v03_character_sheet_async_frontend.py`
- Test: `tests/test_v03_krea_character_sheet.py`
- Add/modify: `tests/test_v03_character_sheet_v2.py` static frontend assertions

**Interfaces:**
- Consumes: `/api/krea-identity/dependency`, `/api/krea-identity/install`, async `/api/generate`, v2 response metadata.
- Produces: v2 request payload, dependency/install state, staged progress UI, advanced legacy selector.

- [ ] **Step 1: Rewrite frontend tests first**

Static/runtime contract must require:

```text
Character Sheet v2 · Identity Edit
Character description
Base sheet
Face detail
Final compose
characterSheetVersion: "v2"
characterSheetDetailer: true
```

and must prove the default path no longer loops over `CHARACTER_SHEET_VIEWS` to submit five base jobs.

- [ ] **Step 2: Run frontend tests and verify RED**

```powershell
python -m unittest tests.test_v03_character_sheet_async_frontend tests.test_v03_krea_character_sheet tests.test_v03_character_sheet_v2 -v
```

Expected: FAIL against the current eight-job sequential/anchor frontend.

- [ ] **Step 3: Implement dependency state + install action**

When Character Sheet is selected:
- query `/api/krea-identity/dependency`;
- show `Ready` when node pack + LoRA are visible;
- otherwise show exact missing component and an `Install Identity Edit` button;
- POST install endpoint;
- when response says `restartRequired=true`, show `Installed — restart StableAMD to activate` and keep Generate disabled for v2.

- [ ] **Step 4: Implement v2 request UI**

Keep task label `Character sheet`; show subtitle `Character Sheet v2 · Identity Edit`.

Add:

```html
<textarea id="krea-character-description" maxlength="600"></textarea>
```

with a neutral-source-pose hint. Hide global Size/Ratio for v2. Keep framing controls hidden because v1.2 `fit` owns base geometry. Under Advanced expose a version selector with `v2` and `legacy-sequential` only during v0.3 acceptance.

- [ ] **Step 5: Replace JS orchestration**

Default v2 sends one async request:

```js
const v2Payload = {
  ...payload,
  editTask: "character-sheet",
  characterSheetVersion: "v2",
  characterDescription: description,
  characterSheetDetailer: true,
  asyncJob: true,
};
delete v2Payload.width;
delete v2Payload.height;
```

Poll the single job normally. Backend owns base/detail/detail/composite orchestration. Progress text should consume stage metadata from job status when present, otherwise display `Character Sheet v2 · generating` rather than inventing a per-view counter.

Legacy selection keeps the existing sequential loop unchanged behind a dedicated function `runLegacyCharacterSheet(...)`.

- [ ] **Step 6: Render final result**

Reuse `renderCharacterSheetResult()`, but summary must show `v2 · Identity Edit` and whether detailer completed/skipped per panel. The final composite remains the primary result image.

- [ ] **Step 7: Run frontend tests**

```powershell
python -m unittest tests.test_v03_character_sheet_async_frontend tests.test_v03_krea_character_sheet tests.test_v03_character_sheet_v2 -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/frontend/app-krea-edit.js tests/test_v03_character_sheet_async_frontend.py tests/test_v03_krea_character_sheet.py tests/test_v03_character_sheet_v2.py
git commit -m "feat: switch Character Sheet UI to v2"
```

---

### Task 6: Packaging, server imports and regression coverage

**Files:**
- Modify: `tests/test_v03_server_isolated_import.py`
- Modify: `tests/StableAmd.Packaging.Tests.ps1`
- Modify: `tests/StableAmd.V03.ModuleImport.Tests.ps1`
- Modify only if packaging requires explicit include: `scripts/Build-StableAMDPackage.ps1`

**Interfaces:**
- Consumes: new backend modules from Tasks 1-4.
- Produces: package/import guarantees that the managed build contains and imports v2 without optional development dependencies.

- [ ] **Step 1: Add failing package/import assertions**

Assert packaged backend contains:

```text
stableamd_v03_krea_identity_edit.py
stableamd_v03_character_sheet_v2.py
```

and isolated import of `stableamd_v03_edit_server` succeeds without Pillow/NumPy being imported at module import time.

- [ ] **Step 2: Run targeted packaging/import tests and verify RED if explicit inclusion is missing**

```powershell
python -m unittest tests.test_v03_server_isolated_import -v
pwsh -NoLogo -NoProfile -Command "Invoke-Pester tests/StableAmd.Packaging.Tests.ps1,tests/StableAmd.V03.ModuleImport.Tests.ps1 -Output Detailed"
```

- [ ] **Step 3: Make the minimum packaging fix**

If `Build-StableAMDPackage.ps1` already copies all backend `*.py`, do not change it; update tests only. If it uses an allow-list, add exactly the two v2 modules and no unrelated files.

- [ ] **Step 4: Run targeted tests again**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_v03_server_isolated_import.py tests/StableAmd.Packaging.Tests.ps1 tests/StableAmd.V03.ModuleImport.Tests.ps1 scripts/Build-StableAMDPackage.ps1
git commit -m "test: package Character Sheet v2 modules"
```

---

### Task 7: Update status, run full CI and prepare physical acceptance

**Files:**
- Modify: `docs/v0.3-status.md`
- Modify: `docs/v0.3-forward-plan.md`
- Modify: PR #4 body

**Interfaces:**
- Consumes: all completed v2 code/tests.
- Produces: accurate project status and target-machine acceptance instructions.

- [ ] **Step 1: Update status docs**

Record:
- v1 sequential/anchor path failed visual identity acceptance;
- v2 uses Identity Edit v1.2 training-matched conditioning;
- automated status vs physical RX 6950 XT status are separate;
- physical acceptance still requires two consecutive full runs and a normal Krea Image Edit after v2.

- [ ] **Step 2: Run the full Python regression suite**

Run the same Python/API command used by `.github/workflows/powershell-tests.yml`; expected: all existing + v2 tests PASS, with only already-documented runtime-library skips.

- [ ] **Step 3: Run full Pester suite**

Run the workflow's Pester command; expected: PASS.

- [ ] **Step 4: Build/package locally or rely on GitHub Actions exactly as workflow defines**

Expected: package build and artifact upload PASS.

- [ ] **Step 5: Commit docs/status changes**

```bash
git add docs/v0.3-status.md docs/v0.3-forward-plan.md
git commit -m "docs: track Character Sheet v2 acceptance"
```

- [ ] **Step 6: Verify the fresh head workflow**

Do not claim completion until the workflow run attached to the exact final head SHA concludes `success`. If Python or Pester fails, inspect the failing job log, fix with a new RED/GREEN cycle, and re-verify the new head.

- [ ] **Step 7: Update draft PR #4**

Replace the current FACE-anchor section with:
- v2 architecture;
- exact pinned Identity Edit dependencies;
- automated CI result/head SHA;
- physical acceptance pending.

- [ ] **Step 8: Physical RX 6950 XT acceptance**

Use the same source photographs that exposed the v1 failure. Acceptance checklist:

```text
[ ] full base + detailer + final compose completes
[ ] source person is recognizably the same in FACE/FRONT/3/4/SIDE
[ ] BACK has no inserted face/portrait
[ ] ghost/grid/debris artifacts materially reduced
[ ] second consecutive v2 run completes
[ ] ordinary Krea Image Edit works immediately after v2
[ ] Gallery shows one final Character Sheet card by default
```

Do not mark v2 target-accepted until every item is checked.
