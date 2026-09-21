# Text-to-SVG v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated StableAMD Vector workspace that turns a text prompt into a real, sanitized, editable Clean SVG by generating a vector-friendly Z-Image raster, converting it with a managed VTracer binary, rendering a PNG preview from the sanitized SVG, and persisting the result in Gallery/history.

**Architecture:** Keep raster generation and vector output as separate contracts. `stableamd_v03_vector.py` owns request validation/orchestration and delegates raster generation to the already accepted Z-Image Turbo provider. `stableamd_v03_svg_vectorizer.py` owns the pinned VTracer dependency and profile-to-CLI mapping. `stableamd_v03_svg_sanitize.py` owns the strict Clean SVG allow-list. `stableamd_v03_svg_preview.py` lazily uses `resvg_py==0.5.0` to render the sanitized SVG into a Gallery PNG. The existing async job transport is generalized just enough to run `text_to_svg` without introducing a second queue.

**Tech Stack:** Python 3.12, existing Z-Image Turbo/ComfyUI provider, VTracer `1.0.0-alpha.4` Windows x64 CLI, Pillow for local raster preprocessing, XML `ElementTree` for sanitized SVG normalization, `resvg_py==0.5.0` for sanitized-SVG preview rendering, vanilla JS/CSS frontend, existing Python unittest + Pester + package CI.

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
- Keep PR #4 draft until the RX 6950 XT physical acceptance checklist is completed.

## Review Focus

- A white shape fully enclosed inside the subject must survive transparent-background processing even if the border background is also white.
- A VTracer output containing `script`, `foreignObject`, `image`, `text`, DTD/entity content, event attributes, unknown namespaces or external URLs must fail sanitization and never be promoted to Gallery.
- Missing/wrong-hash VTracer and missing/wrong-version `resvg_py` must produce an actionable dependency state before wasting time on raster generation.
- A vectorization/sanitization/preview failure after a successful raster generation must not report SVG success; diagnostics/intermediate ownership must remain traceable.
- SVG serving/deletion must never accept arbitrary paths outside `.runtime/stableamd/output`.
- Existing `/api/generate` async behavior and its six-hour Krea timeout injection must remain byte-for-byte compatible from the caller's perspective.

---

### Task 1: Add the managed VTracer + preview dependency contract

**Files:**
- Create: `app/backend/stableamd_v03_svg_vectorizer.py`
- Create: `tests/test_v03_svg_vectorizer.py`

**Interfaces:**
- Produces constants `VECTOR_DEPENDENCY_ID`, `VTRACER_VERSION`, `VTRACER_URL`, `VTRACER_BYTES`, `VTRACER_SHA256`, `RESVG_PY_VERSION`.
- Produces `vector_dependency_status(repo_root: Path) -> dict[str, Any]`.
- Produces `install_vector_dependencies(repo_root: Path, *, urlopen_fn=urlopen, run_fn=subprocess.run) -> dict[str, Any]`.
- Produces `build_vtracer_args(input_path: Path, output_path: Path, detail: str, max_colors: int | None) -> list[str]` and `run_vtracer(...) -> Path`.

Pinned values:

```python
VECTOR_DEPENDENCY_ID = "text-to-svg-v1"
VTRACER_VERSION = "1.0.0-alpha.4"
VTRACER_URL = "https://github.com/visioncortex/vtracer/releases/download/1.0.0-alpha.4/vtracer-x86_64-pc-windows-msvc.zip"
VTRACER_BYTES = 965_231
VTRACER_SHA256 = "8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531"
RESVG_PY_VERSION = "0.5.0"
```

Managed executable path:

```text
.runtime/stableamd/tools/vtracer/1.0.0-alpha.4/vtracer.exe
```

- [ ] **Step 1: Write RED dependency/readiness tests**

Cover:

```python
self.assertEqual(vectorizer.VTRACER_VERSION, "1.0.0-alpha.4")
self.assertEqual(vectorizer.VTRACER_BYTES, 965_231)
self.assertRegex(vectorizer.VTRACER_SHA256, r"^[0-9a-f]{64}$")
self.assertEqual(vectorizer.RESVG_PY_VERSION, "0.5.0")
```

Use a temporary repo root to verify `missing`, `invalid`, and `ready` states. Mock `importlib.metadata.version("resvg_py")` so readiness is true only when the installed version equals `0.5.0`.

Add an installer test with an in-memory/temporary ZIP containing `vtracer.exe`. Verify wrong byte length or SHA256 never promotes the executable and leaves no permanent partial file.

- [ ] **Step 2: Run the new test and verify RED**

```powershell
python -m unittest tests.test_v03_svg_vectorizer -v
```

Expected: import/module failure because `stableamd_v03_svg_vectorizer.py` does not exist.

- [ ] **Step 3: Implement strict managed installation**

Download only the pinned HTTPS URL to a UUID `.partial-*` archive, verify exact bytes and SHA256, inspect ZIP members and reject absolute/`..` traversal paths, extract into a UUID temporary directory, require exactly one usable `vtracer.exe`, then atomically promote the version directory.

Install preview support into the **current StableAMD private interpreter** only when needed:

```python
[
    sys.executable,
    "-m", "pip", "install",
    "--only-binary=:all:",
    "--no-deps",
    "resvg_py==0.5.0",
]
```

After pip returns 0, re-read `importlib.metadata.version("resvg_py")` and require exactly `0.5.0` before returning `ready=True`.

Do not add Rust/Cargo/system Python requirements.

- [ ] **Step 4: Implement StableAMD-owned VTracer profiles**

Map the three product-level detail profiles to fixed CLI arguments:

```python
VTRACER_PROFILES = {
    "simple": ["--preset", "poster", "--mode", "spline", "--filter-speckle", "8", "--simplify", "2.5", "--path-precision", "2", "--optimize", "2"],
    "medium": ["--preset", "poster", "--mode", "spline", "--filter-speckle", "4", "--simplify", "1.5", "--path-precision", "2", "--optimize", "2"],
    "detailed": ["--preset", "poster", "--mode", "spline", "--filter-speckle", "2", "--simplify", "0.75", "--path-precision", "3", "--optimize", "1"],
}
```

`build_vtracer_args()` must append `--max-colors N` only when N is `2`, `4`, `8`, or `16`.

`run_vtracer()` uses `subprocess.run(..., timeout=120, capture_output=True)` and raises `StableAmdBridgeError` with a bounded stderr/stdout tail on non-zero exit or missing output file.

- [ ] **Step 5: Run GREEN tests**

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

**Interfaces:**

```python
@dataclass(frozen=True)
class SanitizedSvg:
    xml: str
    width: int
    height: int
    node_count: int
    path_count: int


def sanitize_svg(
    svg_text: str,
    *,
    max_bytes: int = 2_000_000,
    max_nodes: int = 5_000,
    max_paths: int = 4_000,
) -> SanitizedSvg: ...
```

- [ ] **Step 1: Write RED sanitizer security tests**

Fixtures must independently cover:
- valid `<path>`/basic shapes;
- malformed XML;
- `<!DOCTYPE>` and `<!ENTITY>`;
- `<script>`, event attribute `onclick`;
- `<foreignObject>`, `<image>`, `<text>`, `<tspan>`;
- `<filter>`, `<mask>`, `<clipPath>`, animation;
- `href`, `xlink:href`, `url(...)` and external namespaces;
- non-finite/invalid `viewBox`;
- no drawable shapes;
- over-limit node/path count;
- deterministic output from the same valid fixture.

Representative expectations:

```python
clean = sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#ff0000" d="M0 0L64 0L64 64Z"/></svg>')
self.assertEqual(clean.width, 64)
self.assertEqual(clean.height, 64)
self.assertEqual(clean.path_count, 1)
self.assertNotIn("script", clean.xml.lower())
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_v03_svg_sanitize -v
```

Expected: import/module failure.

- [ ] **Step 3: Implement the allow-list parser/normalizer**

Before XML parsing, reject case-insensitive `<!DOCTYPE` and `<!ENTITY` markers. Parse with stdlib `xml.etree.ElementTree` only after that preflight.

Allowed tags:

```python
ALLOWED_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}
```

Allowed attributes must be tag-scoped. Global safe attributes: `fill`, `stroke`, `stroke-width`, `opacity`, `fill-opacity`, `stroke-opacity`, `transform`, `stroke-linecap`, `stroke-linejoin`. Geometry attrs are allowed only on their relevant shape. Root additionally allows `viewBox`, `width`, `height`, and the canonical SVG namespace.

Reject any attribute name starting with `on`, any `href`, any value containing `url(`, and any namespace other than `http://www.w3.org/2000/svg`.

Require finite four-number `viewBox` with positive width/height. If VTracer supplies only numeric `width` and `height`, derive `viewBox="0 0 W H"`; otherwise reject ambiguous geometry.

Remove comments/metadata/empty groups. Reject if no drawable shape remains.

Serialize deterministically: normalized attribute ordering, canonical namespace and UTF-8 text without DTD.

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

**Interfaces:**

```python
VECTOR_WIDTH = 1024
VECTOR_HEIGHT = 1024
VECTOR_STYLES = {"icon", "illustration"}
VECTOR_DETAILS = {"simple", "medium", "detailed"}
VECTOR_COLOR_LIMITS = {2, 4, 8, 16}


def validate_text_to_svg_request(payload: Any) -> dict[str, Any]: ...
def build_vector_prompt(request: dict[str, Any]) -> str: ...
def prepare_vector_raster(source_path: Path, destination_path: Path, background: str, tolerance: int = 18) -> Path: ...
```

- [ ] **Step 1: Write RED request/prompt tests**

Accept:

```python
{
    "prompt": "a fox curled around a crescent moon",
    "style": "icon",
    "detail": "medium",
    "colors": 4,
    "background": "transparent",
    "seed": 12345,
}
```

Defaults:
- `style="icon"`
- `detail="medium"`
- `colors="auto"`
- `background="transparent"`
- omitted seed remains omitted/randomized downstream
- `backgroundColor="#ffffff"` for solid mode unless explicitly supplied.

Reject extra fields, empty/over-2000-char prompt, unknown enum values, color counts outside `2/4/8/16`, malformed seed and malformed `#RRGGBB` solid color.

Prompt tests must assert both styles add `no text, no letters, no numbers, no watermark`, `flat vector`, `solid shapes`, `crisp edges`, and `no gradients`. `icon` additionally requires one dominant centered symbol/simple silhouette; `illustration` permits multiple objects/full composition.

- [ ] **Step 2: Write RED transparent-background geometry test**

Create a synthetic 64x64 RGB image with white border/background, a colored subject, and an isolated white square completely surrounded by the colored subject. After `prepare_vector_raster(..., background="transparent")`:
- border-connected white pixels have alpha `0`;
- isolated internal white square remains alpha `255`;
- colored subject remains opaque.

- [ ] **Step 3: Run RED**

```powershell
python -m unittest tests.test_v03_vector_request -v
```

Expected: failure because the Vector module/helpers are absent.

- [ ] **Step 4: Implement validation and effective prompt**

Use a server-owned prompt suffix; do not expose raw sampler/scheduler/model knobs through this API. v1 raster size is fixed at `1024x1024` for both styles.

For transparent mode append a clean-background instruction using pure white as the removable border background. For solid mode request the validated `backgroundColor` as a flat full-canvas background.

Do not attempt natural-language censorship of arbitrary user prompts. The product simply does not expose a wordmark/text mode and the server-owned style instruction explicitly forbids text.

- [ ] **Step 5: Implement border-connected background removal**

Lazy-import Pillow inside `prepare_vector_raster`.

Algorithm:
1. convert to RGBA;
2. estimate background reference from the four corners (channel median/mean);
3. seed a queue with border pixels whose RGB channels are each within `tolerance=18` of the reference;
4. flood-fill 4-connected matching pixels only;
5. set alpha=0 only for visited pixels;
6. save an RGBA PNG for VTracer.

For `background="solid"`, copy/normalize the raster to RGBA PNG without alpha removal.

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

**Interfaces:**

```python
def render_svg_preview(svg_text: str, output_path: Path) -> Path: ...
```

- [ ] **Step 1: Write RED preview tests**

Mock a `resvg_py` module whose:

```python
svg_to_bytes(svg_string=...)
```

returns a known PNG byte sequence. Assert `render_svg_preview()` writes those exact bytes atomically and rejects empty/non-PNG output.

Extend isolated-import coverage to assert the final server does **not** eagerly import `resvg_py` or `PIL` merely by loading `stableamd_v03_edit_server.py`.

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_v03_svg_preview tests.test_v03_server_isolated_import -v
```

Expected: new preview module/test fails before implementation.

- [ ] **Step 3: Implement lazy preview rendering**

Inside the function only:

```python
try:
    import resvg_py
except ImportError as exc:
    raise StableAmdBridgeError("SVG preview renderer is not installed. Install the Vector dependency.") from exc

png = resvg_py.svg_to_bytes(svg_string=svg_text)
```

Require PNG signature `b"\x89PNG\r\n\x1a\n"`, write to a UUID temporary sibling, then `replace()` into the final path.

- [ ] **Step 4: Run GREEN**

```powershell
python -m unittest tests.test_v03_svg_preview tests.test_v03_server_isolated_import -v
```

Expected: PASS and isolated import reports no eager Pillow/resvg import.

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

**Interfaces:**
- Add `GenerationJobsApiMixin._submit_bridge_job(request: dict, bridge_method: str, *, job_kind: str) -> dict`.
- Existing `_submit_generation_job(request)` remains and delegates to `_submit_bridge_job(..., "generate", job_kind="generation")`.
- Add `VectorBridgeMixin.text_to_svg(request: dict[str, Any]) -> dict[str, Any]`.
- Add `VectorApiMixin` routes:
  - `GET /api/vector/dependency`
  - `POST /api/vector/install`
  - `POST /api/vector/text-to-svg`

- [ ] **Step 1: RED-test generic async bridge dispatch without changing `/api/generate`**

Add a bridge with both `generate()` and `text_to_svg()`. Assert `_submit_bridge_job(..., "text_to_svg")` runs through the same serialization lock and exposes status/result through the existing `/api/generation-jobs/<id>` endpoints.

Keep the existing test that async `/api/generate` injects `_generationTimeoutSeconds=21600`; Vector jobs must not inject that Krea-specific field unless the Vector orchestrator explicitly needs it for the internal raster request.

- [ ] **Step 2: RED-test Vector API validation and dependency routes**

`POST /api/vector/text-to-svg` validates via `validate_text_to_svg_request`, returns HTTP 202 + job id, and never calls normal `_validate_generation()` for the Vector request body.

`GET /api/vector/dependency` returns the combined VTracer/resvg status.

`POST /api/vector/install` accepts only `{}` or `{"id":"text-to-svg-v1"}` and rejects unknown fields/ids.

- [ ] **Step 3: RED-test orchestration call order**

Use a probe bridge overriding each child step and record calls. Require this order:

```text
dependency-ready
select-zimage
build-prompt
generate-raster
release-runtime
prepare-raster
vtracer
sanitize
preview
persist
hide-intermediate
```

Assert `release-runtime` occurs before `vtracer`.

- [ ] **Step 4: Run RED**

```powershell
python -m unittest tests.test_generation_jobs tests.test_v03_vector_api tests.test_v03_vector_orchestration -v
```

Expected: failures for missing generic job/vector classes.

- [ ] **Step 5: Generalize the existing job runner minimally**

Implement:

```python
def _run_bridge_job(self, job_id, request, bridge_method):
    with self._generation_run_lock:
        ...
        runner = getattr(self.bridge, bridge_method)
        result = runner(request)
        ...


def _submit_bridge_job(self, request, bridge_method, *, job_kind):
    ...
```

Store `jobKind` internally/publicly for diagnostics, but keep the existing status/result URL shape intact. Existing generation tests must still pass without frontend changes.

- [ ] **Step 6: Implement Z-Image selection and raster child generation**

In `VectorBridgeMixin`, choose an installed model whose family is exactly `z-image-turbo` and whose support catalog says `txt2img="supported"`. If none exists, raise an actionable error before vectorization.

Build an internal clean raster request:

```python
{
    "mode": "txt2img",
    "modelId": selected_id,
    "prompt": effective_prompt,
    "width": 1024,
    "height": 1024,
    "seed": seed,
    "startBackendIfNeeded": True,
}
```

Do not pass user LoRAs, ControlNet, Image Edit or Character Sheet fields.

Call the accepted provider via `super().generate(raster_request)` rather than cloning Z-Image graph code into Vector.

- [ ] **Step 7: Implement full Vector orchestration**

Use `.runtime/stableamd/output/vector/` for managed vector outputs and UUID-based working names.

After raster generation:
1. resolve its `ImagePath` as a managed output;
2. call the existing runtime release helper (`_release_character_sheet_runtime()` if that remains the shared `/free` primitive; otherwise add one provider-neutral `_release_comfy_runtime()` wrapper and make Character Sheet delegate to it without behavior change);
3. preprocess background into a Vector working PNG;
4. run VTracer into a temporary raw SVG;
5. read raw SVG and call `sanitize_svg()`;
6. atomically write sanitized SVG;
7. render PNG preview from sanitized SVG;
8. persist history;
9. only after persistence succeeds, mark/hide the raster intermediate from default Gallery.

Return lower-camel product fields plus compatibility Pascal-case where current frontend conventions require it:

```python
{
    "assetType": "svg",
    "provider": "zimage-vtrace",
    "svgPath": str(svg_path),
    "previewPath": str(preview_path),
    "width": sanitized.width,
    "height": sanitized.height,
    "pathCount": sanitized.path_count,
    "nodeCount": sanitized.node_count,
    "sanitized": True,
    "seed": seed,
    "historyPath": str(history_path),
}
```

On vectorization/sanitize/preview failure, never return success and never promote raw SVG. Keep or unhide the raster child/history for diagnosis.

- [ ] **Step 8: Wire final MRO**

In `stableamd_v03_edit_server.py`, import and place `VectorBridgeMixin` before the current Character Sheet layers, and `VectorApiMixin` before the existing API layers. No existing provider method should be overridden for non-Vector requests.

- [ ] **Step 9: Run GREEN**

```powershell
python -m unittest tests.test_generation_jobs tests.test_v03_vector_api tests.test_v03_vector_orchestration -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/backend/stableamd_generation_jobs.py app/backend/stableamd_v03_vector.py app/backend/stableamd_v03_edit_server.py tests/test_generation_jobs.py tests/test_v03_vector_api.py tests/test_v03_vector_orchestration.py
git commit -m "feat: add async Text-to-SVG orchestration"
```

---

### Task 6: Add safe SVG asset serving and Vector-aware Gallery lifecycle

**Files:**
- Modify: `app/backend/stableamd_v03_vector.py`
- Modify: `app/backend/stableamd_server.py` only if the binary/static response hook must be shared with `/api/image`
- Modify: `tests/test_v03_gallery_management.py`
- Create: `tests/test_v03_vector_assets.py`

**Interfaces:**

```python
def resolve_output_svg(repo_root: Path, requested_path: str) -> Path: ...
```

Vector API adds safe product access for sanitized assets. Prefer:
- `GET /api/vector/source?path=...` -> JSON `{ "svg": "<svg..." }` for source viewer;
- `GET /api/vector/asset?path=...` -> raw `image/svg+xml; charset=utf-8` / attachment-capable response using the same loopback HTTP handler mechanism as `/api/image`.

- [ ] **Step 1: Write RED path-safety tests**

Require:
- valid `.svg` under `.runtime/stableamd/output/vector` resolves;
- `.png`, missing file, output root itself, `..`, absolute external path and sibling-directory SVG are rejected;
- source endpoint returns only a sanitized persisted SVG path.

- [ ] **Step 2: Write RED Gallery-delete tests**

Create one vector history record containing:

```json
{
  "assetType": "svg",
  "svgPath": ".../output/vector/a.svg",
  "previewPath": ".../output/vector/a.png",
  "ownedIntermediatePaths": [".../output/vector/a-raster.png"]
}
```

Verify delete removes all managed owned paths plus the record, but refuses to delete an `ownedIntermediatePaths` entry outside the managed output root.

- [ ] **Step 3: Run RED**

```powershell
python -m unittest tests.test_v03_vector_assets tests.test_v03_gallery_management -v
```

Expected: failures because SVG resolver/vector lifecycle are absent.

- [ ] **Step 4: Implement history schema/persistence**

Persist fields from the spec:
- `assetType`, provider, original prompt, effective vector prompt/version;
- style/detail/colors/background/backgroundColor;
- seed;
- `vectorizerVersion`, `sanitizerVersion`;
- `svgPath`, `previewPath`;
- `pathCount`, `nodeCount`;
- child raster prompt/history/path relationship;
- `ownedIntermediatePaths`;
- generation/vectorization/total seconds.

The default Gallery history loader must still accept old raster records unchanged.

- [ ] **Step 5: Implement safe asset/source serving and deletion**

Use `Path.resolve()` and require the StableAMD managed output root to be an ancestor. Serve only `.svg` from the Vector endpoint. Never serve the raw pre-sanitize SVG.

Extend delete logic so Vector-owned managed paths are removed only after containment checks; preserve existing `imagePath` behavior for raster records.

- [ ] **Step 6: Run GREEN**

```powershell
python -m unittest tests.test_v03_vector_assets tests.test_v03_gallery_management -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/backend/stableamd_v03_vector.py app/backend/stableamd_server.py tests/test_v03_vector_assets.py tests/test_v03_gallery_management.py
git commit -m "feat: persist and serve SVG assets safely"
```

---

### Task 7: Build the Vector workspace and SVG Gallery UX

**Files:**
- Create: `app/frontend/app-vector.js`
- Create: `app/frontend/vector.css`
- Modify: `app/frontend/index.html`
- Modify: `app/frontend/app.js`
- Modify: `app/frontend/app-generation-jobs.js`
- Modify: `app/frontend/app-post-actions.js` only for Vector-specific Gallery buttons if needed
- Create: `tests/test_frontend_vector.py`

**Interfaces:**
- Expose `window.StableAmdVector.loadRecord(record)` so Gallery Reuse can switch workspace and restore Vector settings.
- Extend `app-generation-jobs.js` with a reusable `waitForGenerationJob(jobId)` export and async handling for `/api/vector/text-to-svg` without changing `/api/generate` behavior.

- [ ] **Step 1: Write RED frontend contract tests**

Assert `index.html` contains:
- `data-page="vector"` navigation;
- `id="page-vector"`;
- `id="vector-form"`, `vector-prompt`, `vector-style`, `vector-detail`, `vector-colors`, `vector-background`, `vector-seed`;
- `/vector.css` and `/app-vector.js`.

Assert Vector source does **not** contain sampler/scheduler/LoRA/ControlNet controls.

Assert JS contains dependency calls `/api/vector/dependency`, `/api/vector/install`, submission `/api/vector/text-to-svg`, and uses the existing generation-job poll/result URLs.

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_frontend_vector -v
```

Expected: FAIL because Vector workspace does not exist.

- [ ] **Step 3: Add dedicated page/UI**

Add sidebar `Vector` after Generate (before Models) and page metadata:

```javascript
vector: ["Vector", "Create clean editable SVG assets from text prompts."],
```

Vector form controls exactly:

```text
Prompt
Style       Icon / Logo mark | Vector Illustration
Detail      Simple | Medium | Detailed
Colors      Auto | 2 | 4 | 8 | 16
Background  Transparent | Solid
Solid color #RRGGBB (visible only for Solid)
Seed
Generate SVG
```

Show dependency state at top of the Vector form. Missing/invalid dependency disables Generate and offers `Install Vectorizer`.

- [ ] **Step 4: Add async submission/result rendering**

Submit JSON to `/api/vector/text-to-svg`; the shared job helper should poll `/api/generation-jobs/<id>` until completed.

Result pane shows sanitized PNG preview plus metadata and buttons:
- Download SVG;
- View source;
- Regenerate;
- Reuse settings.

Download uses the safe Vector asset endpoint; source viewer fetches `/api/vector/source` and displays escaped text, never `innerHTML` of arbitrary SVG source.

- [ ] **Step 5: Make Gallery vector-aware**

In `makeHistoryVisual(record)`, when `assetType === "svg"`, use `previewPath` through the existing image endpoint instead of `imagePath`.

Add visible `SVG` badge and Vector metadata. Reuse must call `window.StableAmdVector.loadRecord(record)` and `setPage("vector")`.

Do not offer raster-only Img2Img/Inpaint/Outpaint actions for an SVG record unless they intentionally use `previewPath`; v1 should keep the Vector card focused on SVG download/source/reuse/delete.

- [ ] **Step 6: Mobile nav/layout check in CSS**

Current mobile nav is five columns. Increase the mobile grid to six entries only for the six internal page buttons that remain visible; keep `Open ComfyUI` behavior consistent with the existing responsive rules. Ensure Vector form/result collapses to one column below the same breakpoint as Generate.

- [ ] **Step 7: Run GREEN**

```powershell
python -m unittest tests.test_frontend_vector tests.test_frontend_startup_gate -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

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
- Optionally add: `docs/v0.3-text-to-svg-test.md` for the physical acceptance record

**Interfaces:** release/package validation only; do not mark Text-to-SVG target-accepted until the physical checklist passes.

- [ ] **Step 1: Add packaging/import RED tests**

Package assertions must require:

```text
app/backend/stableamd_v03_vector.py
app/backend/stableamd_v03_svg_vectorizer.py
app/backend/stableamd_v03_svg_sanitize.py
app/backend/stableamd_v03_svg_preview.py
app/frontend/app-vector.js
app/frontend/vector.css
```

Isolated import must verify the final server imports without eagerly loading `PIL` or `resvg_py`.

- [ ] **Step 2: Run focused packaging/import checks**

```powershell
python -m unittest tests.test_v03_server_isolated_import -v
Import-Module Pester -MinimumVersion 5.5.0
Invoke-Pester -Path ./tests/StableAmd.Packaging.Tests.ps1 -CI -Output Detailed
```

Expected after implementation: PASS.

- [ ] **Step 3: Run full Python regression suite**

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: zero failures/errors; managed-runtime-only Pillow/resvg physical tests remain mocked/skipped in generic CI as appropriate.

- [ ] **Step 4: Run full Pester suite**

```powershell
Import-Module Pester -MinimumVersion 5.5.0
Invoke-Pester -Path ./tests -CI -Output Detailed
```

Expected: zero failures.

- [ ] **Step 5: Build package**

```powershell
$result = ./scripts/Build-StableAMDPackage.ps1 -Version '0.3.0-text-to-svg-test'
Test-Path $result.ZipPath
```

Expected: `True` and package contains the six Vector files above but no `.runtime`.

- [ ] **Step 6: Update status without premature acceptance**

Document `Text-to-SVG v1` as **implemented / physical acceptance pending**. Keep Character Sheet quality work noted separately and do not rewrite it as accepted.

Create the physical checklist using the exact four classes from the spec:
1. two-color simple icon;
2. text-free logo mark/symbol;
3. 4–8 color flat illustration;
4. detailed vector illustration.

For each, record raster generation time, vectorization time, final path/node counts, background result, SVG/preview screenshots, and whether ordinary Z-Image + Krea generation still work immediately afterward.

- [ ] **Step 7: Commit implementation-status docs/tests**

```bash
git add tests/StableAmd.Packaging.Tests.ps1 tests/test_v03_server_isolated_import.py docs/v0.3-status.md docs/v0.3-forward-plan.md docs/v0.3-text-to-svg-test.md
git commit -m "test: gate Text-to-SVG v1 release packaging"
```

If the optional physical record file was not created yet, omit it from `git add`; do not create a fake acceptance result.

- [ ] **Step 8: Verify exact-head CI before handing off to physical test**

Wait for the PR-triggered GitHub Actions run for the exact current head. Verify:
- Parse PowerShell files: success;
- Compile Python probes: success;
- Python API tests: success;
- Pester install/tests: success;
- package build: success;
- artifact upload: success.

Add a PR #4 status comment containing the exact head SHA, the RED/GREEN test evidence and `physical Text-to-SVG acceptance pending`.

---

## Physical Acceptance Command / User Handoff

After exact-head CI is green, the target-machine update is:

```powershell
Ctrl+C
git pull
.\Start-StableAMD.cmd
```

Because Task 7 changes frontend files, use **Ctrl+F5 once** after the application has restarted.

First visit **Vector → Text to SVG**. If dependency state is missing, use **Install Vectorizer** and let StableAMD install pinned VTracer + `resvg_py==0.5.0`; restart only if the dependency response explicitly says it is required.

Do not mark Text-to-SVG `target-accepted` until all four physical samples produce useful editable SVGs, Gallery lifecycle works, and ordinary Z-Image + Krea still work afterwards.
