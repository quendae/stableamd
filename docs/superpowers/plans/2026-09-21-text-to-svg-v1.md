# Text-to-SVG v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated StableAMD Vector workspace that turns a text prompt into a real, sanitized, editable Clean SVG by generating a vector-friendly Z-Image raster, converting it with a managed VTracer binary, rendering a PNG preview from the sanitized SVG, and persisting the result in Gallery/history.

**Architecture:** Keep raster generation and vector output as separate contracts. `stableamd_v03_vector.py` owns request validation/orchestration and delegates raster generation to the already accepted Z-Image Turbo provider. `stableamd_v03_svg_vectorizer.py` owns the pinned VTracer dependency and profile-to-CLI mapping. `stableamd_v03_svg_sanitize.py` owns the strict Clean SVG allow-list. `stableamd_v03_svg_preview.py` lazily uses `resvg_py==0.5.0` to render the sanitized SVG into a Gallery PNG. The existing async job transport is generalized only enough to run `text_to_svg` without introducing a second queue.

**Tech Stack:** Python 3.12, existing Z-Image Turbo/ComfyUI provider, VTracer `1.0.0-alpha.4` Windows x64 CLI, Pillow for local raster preprocessing, stdlib `xml.etree.ElementTree` for SVG normalization, `resvg_py==0.5.0` for sanitized-SVG preview rendering, vanilla JS/CSS frontend, existing Python unittest + Pester + package CI.

**Spec:** `docs/superpowers/specs/2026-09-21-text-to-svg-v1-design.md`

## Global Constraints

- Physical target remains Windows + Radeon RX 6950 XT 16 GiB (`gfx1030`).
- Do not alter accepted Z-Image/Krea generation defaults globally to make Vector work.
- v1 supports `icon` and `illustration`; wordmarks/text, diagrams/infographics, Image-to-SVG and direct-SVG foundation models remain out of scope.
- Final product asset must be real vector geometry; `<image>`, embedded raster data, external resources, scripts, text and active SVG content are forbidden.
- VTracer is CPU-side post-processing. Release ComfyUI runtime memory after raster generation and before vectorization.
- Raster intermediate must not become the visible final Gallery result when SVG finalization succeeds.
- `colors` values `2/4/8/16` mean **at most N colors** via VTracer `--max-colors`; `auto` omits the flag.
- `background="transparent"` means StableAMD removes only border-connected background pixels before VTracer. It must never globally delete every pixel matching the background color.
- Vector preview must be rendered from the **sanitized final SVG**, never from the original raster intermediate.
- Optional libraries (`PIL`, `resvg_py`) must be imported lazily so the final v0.3 server still imports under generic CI without those managed-runtime packages.
- The public Vector result uses lower-camel-case fields only. Do not introduce a second PascalCase Vector contract.
- Keep PR #4 draft until the RX 6950 XT physical acceptance checklist is completed.

## Review Focus

- A white shape fully enclosed inside the subject must survive transparent-background processing even if the border background is also white.
- A VTracer output containing `script`, `foreignObject`, `image`, `text`, DTD/entity content, event attributes, unknown namespaces or external URLs must fail sanitization and never be promoted to Gallery.
- Missing/wrong-hash VTracer and missing/wrong-version `resvg_py` must produce an actionable dependency state before raster generation starts.
- A vectorization/sanitization/preview failure after a successful raster generation must not report SVG success; diagnostics/intermediate ownership must remain traceable.
- SVG source lookup/deletion must never accept arbitrary paths outside `.runtime/stableamd/output`.
- Existing `/api/generate` async behavior and its six-hour Krea timeout injection must remain compatible from the caller's perspective.

---

### Task 1: Add the managed VTracer + preview dependency contract

**Files:**
- Create: `app/backend/stableamd_v03_svg_vectorizer.py`
- Create: `tests/test_v03_svg_vectorizer.py`

**Required interfaces:**
- constants: `VECTOR_DEPENDENCY_ID`, `VTRACER_VERSION`, `VTRACER_URL`, `VTRACER_BYTES`, `VTRACER_SHA256`, `RESVG_PY_VERSION`;
- `vector_dependency_status(repo_root: Path) -> dict[str, Any]`;
- `install_vector_dependencies(repo_root: Path, *, urlopen_fn=urlopen, run_fn=subprocess.run) -> dict[str, Any]`;
- `build_vtracer_args(input_path: Path, output_path: Path, detail: str, max_colors: int | None) -> list[str]`;
- `run_vtracer(repo_root: Path, input_path: Path, output_path: Path, *, detail: str, max_colors: int | None, run_fn=subprocess.run) -> Path`.

Pinned values:

```python
VECTOR_DEPENDENCY_ID = "text-to-svg-v1"
VTRACER_VERSION = "1.0.0-alpha.4"
VTRACER_URL = "https://github.com/visioncortex/vtracer/releases/download/1.0.0-alpha.4/vtracer-x86_64-pc-windows-msvc.zip"
VTRACER_BYTES = 965_231
VTRACER_SHA256 = "8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531"
RESVG_PY_VERSION = "0.5.0"
```

Managed executable:

```text
.runtime/stableamd/tools/vtracer/1.0.0-alpha.4/vtracer.exe
```

Dependency status shape:

```json
{
  "id": "text-to-svg-v1",
  "ready": false,
  "status": "missing",
  "restartRequired": false,
  "vtracer": {"status": "missing", "version": "1.0.0-alpha.4"},
  "previewRenderer": {"status": "missing", "package": "resvg_py", "version": "0.5.0"}
}
```

Allowed top-level states are exactly `ready`, `missing`, `invalid`. Installation into the already-running private Python does not require a restart because `resvg_py` is imported lazily; successful install returns `restartRequired=false`.

- [ ] **Step 1: Write RED dependency/readiness tests**

Cover pinned constants, managed path, `missing`, `invalid`, `ready`, and exact `resvg_py==0.5.0` version detection via mocked `importlib.metadata.version`.

Add an installer test using a temporary ZIP containing `vtracer.exe`. Verify wrong byte length or SHA256 never promotes the executable and leaves no permanent partial archive/directory.

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_v03_svg_vectorizer -v
```

Expected: import/module failure before implementation.

- [ ] **Step 3: Implement strict managed installation**

Download only the pinned HTTPS URL to a UUID `.partial-*` archive, verify exact bytes and SHA256, reject absolute/`..` ZIP paths, extract to a UUID temporary directory, require exactly one usable `vtracer.exe`, then atomically promote the version directory.

Install preview support with the current StableAMD private interpreter:

```python
[
    sys.executable,
    "-m", "pip", "install",
    "--only-binary=:all:",
    "--no-deps",
    "resvg_py==0.5.0",
]
```

After pip exit code 0, re-read `importlib.metadata.version("resvg_py")` and require exactly `0.5.0` before returning ready. Do not add Rust/Cargo/system Python requirements.

- [ ] **Step 4: Implement StableAMD-owned VTracer profiles**

```python
VTRACER_PROFILES = {
    "simple": ["--preset", "poster", "--mode", "spline", "--filter-speckle", "8", "--simplify", "2.5", "--path-precision", "2", "--optimize", "2"],
    "medium": ["--preset", "poster", "--mode", "spline", "--filter-speckle", "4", "--simplify", "1.5", "--path-precision", "2", "--optimize", "2"],
    "detailed": ["--preset", "poster", "--mode", "spline", "--filter-speckle", "2", "--simplify", "0.75", "--path-precision", "3", "--optimize", "1"],
}
```

Append `--max-colors N` only for `2`, `4`, `8`, `16`. `auto` omits it.

Run VTracer with `timeout=120`, captured stdout/stderr, and raise `StableAmdBridgeError` with a bounded output tail for non-zero exit, timeout, or missing output SVG.

- [ ] **Step 5: Run GREEN**

```powershell
python -m unittest tests.test_v03_svg_vectorizer -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/backend/stableamd_v03_svg_vectorizer.py tests/test_v03_svg_vectorizer.py
git commit -m "feat: add managed SVG vectorizer dependency"
```

---

### Task 2: Implement the strict Clean SVG sanitizer

**Files:**
- Create: `app/backend/stableamd_v03_svg_sanitize.py`
- Create: `tests/test_v03_svg_sanitize.py`

**Required interfaces:**
- `SANITIZER_VERSION = "clean-svg-v1"`;
- immutable `SanitizedSvg` with `xml`, `width`, `height`, `node_count`, `path_count`;
- `sanitize_svg(svg_text: str, *, max_bytes: int = 2_000_000, max_nodes: int = 5_000, max_paths: int = 4_000) -> SanitizedSvg`.

- [ ] **Step 1: Write RED sanitizer security tests**

Fixtures independently cover valid basic shapes, malformed XML, `DOCTYPE`, `ENTITY`, `script`, `onclick`, `foreignObject`, `image`, `text`, `tspan`, `filter`, `mask`, `clipPath`, animation, `href`, `xlink:href`, `url(...)`, unknown namespaces/elements, non-finite/invalid `viewBox`, empty geometry, complexity limits, and deterministic normalized output.

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_v03_svg_sanitize -v
```

Expected: import/module failure.

- [ ] **Step 3: Implement the allow-list parser/normalizer**

Before XML parsing, reject case-insensitive `<!DOCTYPE` and `<!ENTITY`. Parse with stdlib `xml.etree.ElementTree` only after preflight.

Allowed tags:

```python
ALLOWED_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}
```

Allowed attributes are tag-scoped. Global safe presentation attributes are `fill`, `stroke`, `stroke-width`, `opacity`, `fill-opacity`, `stroke-opacity`, `transform`, `stroke-linecap`, `stroke-linejoin`. Geometry attributes are allowed only on their relevant shapes. Root additionally allows `viewBox`, `width`, `height` and canonical SVG namespace handling.

Reject any attribute beginning with `on`, any `href`, any value containing `url(`, and any namespace other than `http://www.w3.org/2000/svg`.

Require finite four-number `viewBox` with positive width/height. If input has only numeric `width` and `height`, derive `viewBox="0 0 W H"`; otherwise reject ambiguous geometry.

Remove comments/metadata/empty groups. Reject if no drawable geometry remains. Serialize with deterministic attribute ordering and no DTD.

- [ ] **Step 4: Run GREEN**

```powershell
python -m unittest tests.test_v03_svg_sanitize -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stableamd_v03_svg_sanitize.py tests/test_v03_svg_sanitize.py
git commit -m "feat: add clean SVG sanitizer"
```

---

### Task 3: Add Text-to-SVG request validation, prompt construction and raster preprocessing

**Files:**
- Create: `app/backend/stableamd_v03_vector.py`
- Create: `tests/test_v03_vector_request.py`

**Required constants/interfaces:**
- `VECTOR_PROMPT_VERSION = "text-to-svg-v1"`;
- `VECTOR_WIDTH = 1024`, `VECTOR_HEIGHT = 1024`;
- styles `icon`, `illustration`;
- detail levels `simple`, `medium`, `detailed`;
- color limits `2`, `4`, `8`, `16`;
- `validate_text_to_svg_request(payload: Any) -> dict[str, Any]`;
- `build_vector_prompt(request: dict[str, Any]) -> str`;
- `prepare_vector_raster(source_path: Path, destination_path: Path, background: str, tolerance: int = 18) -> Path`.

- [ ] **Step 1: Write RED request/prompt tests**

Accept a request with prompt/style/detail/colors/background/seed. Defaults are `style="icon"`, `detail="medium"`, `colors="auto"`, `background="transparent"`; omitted seed stays omitted for downstream randomization; solid background defaults to `#ffffff`.

Reject extra fields, empty/over-2000-char prompt, unknown enums, color counts outside `2/4/8/16`, malformed seed and malformed `#RRGGBB` solid color.

Prompt tests assert both styles add `no text, no letters, no numbers, no watermark`, `flat vector`, `solid shapes`, `crisp edges`, and `no gradients`. Icon additionally requires one dominant centered symbol/simple silhouette; illustration permits multiple objects/full composition.

- [ ] **Step 2: Write RED transparent-background geometry test**

Create a synthetic 64x64 image with white border/background, a colored subject, and an isolated white square fully enclosed by the subject. After transparent preprocessing, border-connected white pixels must be alpha `0`, while the isolated internal white square and colored subject remain alpha `255`.

- [ ] **Step 3: Run RED**

```powershell
python -m unittest tests.test_v03_vector_request -v
```

Expected: failure because Vector helpers are absent.

- [ ] **Step 4: Implement validation and effective prompt**

Use a server-owned vector suffix; no sampler/scheduler/model/LoRA knobs in this API. Raster size is fixed at `1024x1024` for both styles.

Transparent mode explicitly requests a pure-white flat background suitable for border removal. Solid mode explicitly requests the validated `backgroundColor` across the full canvas.

Do not attempt natural-language censorship of arbitrary prompts. v1 simply has no text/wordmark mode and its server-owned instruction forbids text.

- [ ] **Step 5: Implement border-connected background removal**

Lazy-import Pillow inside `prepare_vector_raster`.

Algorithm:
1. convert to RGBA;
2. estimate background reference from the four corners using channel medians;
3. seed a queue with matching border pixels whose per-channel difference is within `tolerance=18`;
4. flood-fill 4-connected matching pixels only;
5. set alpha=0 only for visited pixels;
6. save RGBA PNG for VTracer.

For solid background, normalize/copy to RGBA PNG without alpha removal.

- [ ] **Step 6: Run GREEN**

```powershell
python -m unittest tests.test_v03_vector_request -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/backend/stableamd_v03_vector.py tests/test_v03_vector_request.py
git commit -m "feat: add Text-to-SVG request and raster preparation"
```

---

### Task 4: Render PNG preview from sanitized SVG with lazy resvg_py

**Files:**
- Create: `app/backend/stableamd_v03_svg_preview.py`
- Create: `tests/test_v03_svg_preview.py`
- Modify: `tests/test_v03_server_isolated_import.py`

**Required interface:** `render_svg_preview(svg_text: str, output_path: Path) -> Path`.

- [ ] **Step 1: Write RED preview tests**

Mock `resvg_py.svg_to_bytes(svg_string=...)` to return known PNG bytes. Assert the preview function writes those bytes atomically and rejects empty/non-PNG output.

Extend isolated-import coverage to assert final server loading does not eagerly import `resvg_py` or `PIL`.

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_v03_svg_preview tests.test_v03_server_isolated_import -v
```

Expected: preview module/test fails before implementation.

- [ ] **Step 3: Implement lazy preview rendering**

Inside the function, import `resvg_py`; on `ImportError`, raise `StableAmdBridgeError("SVG preview renderer is not installed. Install the Vector dependency.")`.

Call `resvg_py.svg_to_bytes(svg_string=svg_text)`, require PNG signature `b"\x89PNG\r\n\x1a\n"`, write to UUID temporary sibling, then atomically replace the final preview path.

- [ ] **Step 4: Run GREEN**

```powershell
python -m unittest tests.test_v03_svg_preview tests.test_v03_server_isolated_import -v
```

Expected: PASS, with no eager Pillow/resvg import.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stableamd_v03_svg_preview.py tests/test_v03_svg_preview.py tests/test_v03_server_isolated_import.py
git commit -m "feat: render sanitized SVG previews"
```

---

### Task 5: Generalize async jobs and implement Text-to-SVG orchestration/API

**Files:**
- Modify: `app/backend/stableamd_generation_jobs.py`
- Modify: `app/backend/stableamd_v03_vector.py`
- Modify: `app/backend/stableamd_v03_edit_server.py`
- Modify: `tests/test_generation_jobs.py`
- Create: `tests/test_v03_vector_api.py`
- Create: `tests/test_v03_vector_orchestration.py`

**Required interfaces:**
- `GenerationJobsApiMixin._submit_bridge_job(request: dict, bridge_method: str, *, job_kind: str) -> dict`;
- existing `_submit_generation_job(request)` delegates to `_submit_bridge_job(request, "generate", job_kind="generation")`;
- `VectorBridgeMixin._release_vector_runtime() -> bool`;
- `VectorBridgeMixin.text_to_svg(request: dict[str, Any]) -> dict[str, Any]`;
- `VectorApiMixin` routes `GET /api/vector/dependency`, `POST /api/vector/install`, `POST /api/vector/text-to-svg`.

- [ ] **Step 1: RED-test generic async bridge dispatch without changing `/api/generate`**

Add a bridge with both `generate()` and `text_to_svg()`. Assert `_submit_bridge_job(request, "text_to_svg", job_kind="vector")` uses the same serialization lock and existing `/api/generation-jobs/<id>` status/result endpoints.

Keep the existing assertion that async `/api/generate` injects `_generationTimeoutSeconds=21600`. Vector job request objects themselves must not receive that Krea-specific field.

- [ ] **Step 2: RED-test Vector API validation and dependency routes**

`POST /api/vector/text-to-svg` validates only the Vector request contract and returns HTTP 202 + job id. It must not route the Vector body through raster `_validate_generation()`.

`GET /api/vector/dependency` returns combined VTracer/resvg readiness. `POST /api/vector/install` accepts only `{}` or `{"id":"text-to-svg-v1"}`.

- [ ] **Step 3: RED-test orchestration call order**

Probe bridge required order:

```text
dependency-ready
select-zimage
build-prompt
generate-raster
release-vector-runtime
prepare-raster
vtracer
sanitize
preview
persist
hide-intermediate
```

Assert runtime release occurs before VTracer.

- [ ] **Step 4: Run RED**

```powershell
python -m unittest tests.test_generation_jobs tests.test_v03_vector_api tests.test_v03_vector_orchestration -v
```

Expected: failures for missing generic job/vector classes.

- [ ] **Step 5: Generalize existing job runner minimally**

Preserve existing job dictionary keys/status semantics. New method behavior is concrete:

```python
def _run_bridge_job(self, job_id, request, bridge_method):
    job = self._generation_jobs[job_id]
    job["status"] = "running"
    job["startedAt"] = time.time()
    try:
        with self._generation_run_lock:
            result = getattr(self.bridge, bridge_method)(request)
        job["result"] = result
        job["status"] = "completed"
    except Exception as exc:
        job["error"] = str(exc)
        job["status"] = "failed"
    finally:
        job["finishedAt"] = time.time()
```

When implementing, keep whatever timestamp key names already exist in the current runner rather than renaming them; the behavior above is the required flow. `_submit_bridge_job` creates the same job envelope as `_submit_generation_job`, adds `jobKind`, starts the worker thread with `bridge_method`, and returns the existing submission shape.

- [ ] **Step 6: Implement Z-Image selection and raster child generation**

Choose an installed model with family exactly `z-image-turbo` whose support catalog says `txt2img="supported"`. If none exists, raise an actionable error before starting the job's raster stage.

Internal raster request contains only:

```python
{
    "mode": "txt2img",
    "modelId": selected_id,
    "prompt": effective_prompt,
    "width": 1024,
    "height": 1024,
    "seed": resolved_seed,
}
```

Do not pass user LoRAs, Control, Image Edit or Character Sheet fields. Call the accepted provider through `super().generate(raster_request)`; do not clone the Z-Image graph.

- [ ] **Step 7: Implement Vector-local runtime release**

Do **not** refactor or call `_release_character_sheet_runtime()`.

`VectorBridgeMixin._release_vector_runtime()` independently calls:

```python
self._post_comfy_no_content(
    "free",
    {"unload_models": True, "free_memory": True},
    timeout=10,
)
```

Return `False` on unavailable helper/OSError/StableAmdBridgeError and `True` on success, matching the non-fatal cleanup semantics already proven elsewhere.

- [ ] **Step 8: Implement full Vector orchestration**

Final/working Vector outputs live under `.runtime/stableamd/output/vector/` with UUID names. The child Z-Image raster may remain at its existing managed output location.

After raster generation:
1. validate child `ImagePath` through existing managed-image resolver;
2. release Vector runtime;
3. preprocess to Vector working PNG;
4. run VTracer to a raw temporary SVG;
5. sanitize raw SVG;
6. atomically write the sanitized final SVG;
7. render PNG preview from sanitized SVG;
8. persist final Vector history;
9. only after persistence succeeds, update child history `galleryHidden=true` and link it to final Vector prompt id.

On vectorizer/sanitizer/preview/persistence failure, do not report SVG success and leave child raster/history visible or recoverable for diagnosis. Raw VTracer SVG is never promoted.

Public result fields are exactly lower-camel:

```json
{
  "assetType": "svg",
  "provider": "zimage-vtrace",
  "svgPath": "...",
  "previewPath": "...",
  "width": 1024,
  "height": 1024,
  "pathCount": 37,
  "nodeCount": 42,
  "sanitized": true,
  "seed": 12345,
  "historyPath": "..."
}
```

- [ ] **Step 9: Wire final MRO**

In `stableamd_v03_edit_server.py`, put `VectorBridgeMixin` before current Character Sheet layers and `VectorApiMixin` before current API layers. Non-Vector provider behavior must delegate unchanged.

- [ ] **Step 10: Run GREEN**

```powershell
python -m unittest tests.test_generation_jobs tests.test_v03_vector_api tests.test_v03_vector_orchestration -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add app/backend/stableamd_generation_jobs.py app/backend/stableamd_v03_vector.py app/backend/stableamd_v03_edit_server.py tests/test_generation_jobs.py tests/test_v03_vector_api.py tests/test_v03_vector_orchestration.py
git commit -m "feat: add async Text-to-SVG orchestration"
```

---

### Task 6: Add safe SVG source access and Vector-aware Gallery lifecycle

**Files:**
- Modify: `app/backend/stableamd_v03_vector.py`
- Modify: `app/backend/stableamd_server.py`
- Modify: `tests/test_v03_gallery_management.py`
- Create: `tests/test_v03_vector_assets.py`

**Required interfaces:**
- `resolve_output_svg(repo_root: Path, requested_path: str) -> Path`;
- `GET /api/vector/source?path=...` returns JSON `{ "fileName": "name.svg", "svg": "<svg ...>" }`.

There is deliberately **no raw SVG HTTP rendering endpoint in v1**. Download uses the JSON source route and a browser-created Blob. This keeps active SVG out of direct document navigation while still allowing source/download.

- [ ] **Step 1: Write RED path-safety tests**

Require valid `.svg` under `.runtime/stableamd/output/vector` to resolve. Reject PNG, missing files, root directory, `..`, external absolute path and SVG outside the Vector subdirectory.

Source endpoint must return only sanitized persisted SVGs under that resolver.

- [ ] **Step 2: Write RED Gallery-delete tests**

Vector history record contains `assetType`, `svgPath`, `previewPath`, and `ownedIntermediatePaths`.

Delete removes final SVG, preview and owned managed intermediates plus history. If any owned path resolves outside `.runtime/stableamd/output`, refuse that path and never delete arbitrary external content. Existing raster `imagePath` deletion remains unchanged.

- [ ] **Step 3: Run RED**

```powershell
python -m unittest tests.test_v03_vector_assets tests.test_v03_gallery_management -v
```

Expected: failures before SVG lifecycle support.

- [ ] **Step 4: Implement history schema/persistence**

Persist:
- `assetType="svg"`, provider;
- original prompt and effective prompt plus `VECTOR_PROMPT_VERSION`;
- style/detail/colors/background/backgroundColor;
- seed;
- `vectorizerVersion=VTRACER_VERSION`;
- `sanitizerVersion=SANITIZER_VERSION`;
- `svgPath`, `previewPath`, path/node counts;
- child raster history/path relationship;
- `ownedIntermediatePaths`;
- generation/vectorization/total seconds;
- `galleryHidden=false` for final record.

Keep old raster history compatible.

- [ ] **Step 5: Implement safe source route and deletion**

`resolve_output_svg()` requires `.runtime/stableamd/output/vector` as ancestor and `.svg` suffix. `/api/vector/source` reads only through this resolver and returns JSON string content.

For deletion, `svgPath` must pass the Vector resolver; `previewPath` and `ownedIntermediatePaths` may be any descendant of the broader `.runtime/stableamd/output` root because the accepted Z-Image child raster is not necessarily in the Vector subfolder.

- [ ] **Step 6: Run GREEN**

```powershell
python -m unittest tests.test_v03_vector_assets tests.test_v03_gallery_management -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/backend/stableamd_v03_vector.py app/backend/stableamd_server.py tests/test_v03_vector_assets.py tests/test_v03_gallery_management.py
git commit -m "feat: persist and access SVG assets safely"
```

---

### Task 7: Build the Vector workspace and SVG Gallery UX

**Files:**
- Create: `app/frontend/app-vector.js`
- Create: `app/frontend/vector.css`
- Modify: `app/frontend/index.html`
- Modify: `app/frontend/app.js`
- Modify: `app/frontend/app-generation-jobs.js`
- Modify: `app/frontend/app-post-actions.js`
- Create: `tests/test_frontend_vector.py`

**Required browser interfaces:**
- `window.StableAmdJobs.waitForGenerationJob(jobId)`;
- `window.StableAmdVector.loadRecord(record)`.

- [ ] **Step 1: Write RED frontend contract tests**

Assert `index.html` contains Vector navigation/page/form controls and `/vector.css`, `/app-vector.js`.

Assert Vector module contains no sampler/scheduler/LoRA/ControlNet controls and calls `/api/vector/dependency`, `/api/vector/install`, `/api/vector/text-to-svg`, and existing generation-job status/result endpoints.

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_frontend_vector -v
```

Expected: FAIL before Vector UI exists.

- [ ] **Step 3: Export shared async waiter**

Keep existing `/api/generate` interception behavior. In `app-generation-jobs.js`, publish:

```javascript
window.StableAmdJobs = { waitForGenerationJob };
```

`app-vector.js` submits `/api/vector/text-to-svg`; if response contains `jobId`, it calls the shared waiter. Do not make the global API wrapper inject raster `asyncJob` into Vector requests.

- [ ] **Step 4: Add dedicated Vector page**

Add sidebar `Vector` after Generate and page metadata:

```javascript
vector: ["Vector", "Create clean editable SVG assets from text prompts."],
```

Controls exactly:

```text
Prompt
Style       Icon / Logo mark | Vector Illustration
Detail      Simple | Medium | Detailed
Colors      Auto | 2 | 4 | 8 | 16
Background  Transparent | Solid
Solid color #RRGGBB (shown only for Solid)
Seed
Generate SVG
```

Dependency state is shown at top. Missing/invalid disables Generate and shows `Install Vectorizer`.

- [ ] **Step 5: Add result rendering/download/source**

Result pane displays `previewPath` through `/api/image` plus vector metadata.

For Download SVG and View source, fetch `/api/vector/source?path=...`. Display source with `textContent`, never `innerHTML`.

Download creates:

```javascript
const blob = new Blob([payload.svg], { type: "image/svg+xml;charset=utf-8" });
```

then triggers a temporary `<a download="...svg">` object-URL download and revokes the URL afterward.

- [ ] **Step 6: Make Gallery Vector-aware**

`makeHistoryVisual(record)` uses `previewPath` for `assetType="svg"`; add SVG badge and vector metadata.

`app-post-actions.js` explicitly detects `assetType="svg"`, suppresses raster-only Img2Img/Inpaint/Outpaint/Upscale actions, and renders Vector Download / View source / Reuse / Delete actions. Reuse calls `StableAmdVector.loadRecord(record)` and switches to `setPage("vector")`.

- [ ] **Step 7: Mobile layout**

Current mobile nav is five columns. Change it to six for Generate, Vector, Models, Gallery, Settings, Diagnostics while preserving existing Open ComfyUI responsive behavior. Vector form/result collapses to one column at the same breakpoint as Generate.

- [ ] **Step 8: Run GREEN**

```powershell
python -m unittest tests.test_frontend_vector tests.test_frontend_startup_gate -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/frontend/app-vector.js app/frontend/vector.css app/frontend/index.html app/frontend/app.js app/frontend/app-generation-jobs.js app/frontend/app-post-actions.js tests/test_frontend_vector.py
git commit -m "feat: add Vector Text-to-SVG workspace"
```

---

### Task 8: Package, regression-test and stage RX 6950 XT acceptance

**Files:**
- Modify: `tests/StableAmd.Packaging.Tests.ps1`
- Modify: `tests/test_v03_server_isolated_import.py`
- Modify: `docs/v0.3-status.md`
- Modify: `docs/v0.3-forward-plan.md`
- Create: `docs/v0.3-text-to-svg-test.md`

Do not mark Text-to-SVG target-accepted until physical checks pass.

- [ ] **Step 1: Add packaging/import RED tests**

Package assertions require:

```text
app/backend/stableamd_v03_vector.py
app/backend/stableamd_v03_svg_vectorizer.py
app/backend/stableamd_v03_svg_sanitize.py
app/backend/stableamd_v03_svg_preview.py
app/frontend/app-vector.js
app/frontend/vector.css
```

Isolated import requires `PIL` and `resvg_py` to remain unloaded when final server is imported.

- [ ] **Step 2: Create physical acceptance worksheet**

`docs/v0.3-text-to-svg-test.md` contains unchecked fields only; it must not claim any physical pass before user testing.

Four required samples:
1. two-color simple icon;
2. text-free logo mark/symbol;
3. 4–8 color flat illustration;
4. detailed vector illustration.

For each record raster generation time, vectorization time, final path/node counts, background behavior, SVG/preview result, Gallery reuse/delete, and post-test ordinary Z-Image + Krea health.

- [ ] **Step 3: Run focused package/import checks**

```powershell
python -m unittest tests.test_v03_server_isolated_import -v
Import-Module Pester -MinimumVersion 5.5.0
Invoke-Pester -Path ./tests/StableAmd.Packaging.Tests.ps1 -CI -Output Detailed
```

Expected: PASS.

- [ ] **Step 4: Run full Python regression suite**

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: zero failures/errors.

- [ ] **Step 5: Run full Pester suite**

```powershell
Import-Module Pester -MinimumVersion 5.5.0
Invoke-Pester -Path ./tests -CI -Output Detailed
```

Expected: zero failures.

- [ ] **Step 6: Build package**

```powershell
$result = ./scripts/Build-StableAMDPackage.ps1 -Version '0.3.0-text-to-svg-test'
Test-Path $result.ZipPath
```

Expected: `True`, six Vector files present, no `.runtime` in package.

- [ ] **Step 7: Update status without premature acceptance**

Document Text-to-SVG v1 as `implemented / physical acceptance pending`. Keep Character Sheet quality work separately pending; do not rewrite it as accepted.

- [ ] **Step 8: Commit status/tests**

```bash
git add tests/StableAmd.Packaging.Tests.ps1 tests/test_v03_server_isolated_import.py docs/v0.3-status.md docs/v0.3-forward-plan.md docs/v0.3-text-to-svg-test.md
git commit -m "test: gate Text-to-SVG v1 release packaging"
```

- [ ] **Step 9: Verify exact-head CI before physical handoff**

Wait for PR-triggered Actions on the exact current head and verify all six workflow stages: PowerShell parse, Python probes, Python tests, Pester tests, package build, artifact upload.

Add a PR #4 status comment with exact head SHA, RED/GREEN evidence and `physical Text-to-SVG acceptance pending`.

---

## Physical Acceptance Command / User Handoff

After exact-head CI is green:

```powershell
Ctrl+C
git pull
.\Start-StableAMD.cmd
```

Task 7 changes frontend files, so use **Ctrl+F5 once** after restart.

Open **Vector → Text to SVG**. If dependency state is missing/invalid, use **Install Vectorizer**; StableAMD installs pinned VTracer + `resvg_py==0.5.0` without requiring an application restart.

Do not mark Text-to-SVG `target-accepted` until all four physical samples produce useful editable SVGs, Gallery lifecycle works, and ordinary Z-Image + Krea still work afterwards.
