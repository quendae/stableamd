# StableAMD Image-to-SVG v1 Design

Date: 2026-09-22
Status: design approved in conversation; implementation not yet started
Target: Windows + AMD Radeon RX 6950 XT 16 GiB (`gfx1030`)
Branch: `feat/stableamd-v0.3`

## 1. Purpose

Image-to-SVG extends the target-accepted Vector workspace so an existing raster image can be converted into a sanitized, editable Clean SVG without requiring a text prompt.

The feature must reuse the accepted Text-to-SVG vector stack instead of creating a second SVG pipeline:

```text
managed raster source
  -> crop / source normalization
  -> mode-specific preprocessing
  -> optional background removal
  -> VTracer
  -> Clean SVG sanitizer
  -> resvg_py preview
  -> Vector Gallery/history
```

The default path is deterministic and local. Generative processing is opt-in and isolated to the Creative photo mode.

## 2. User goals and success criteria

A user must be able to:

1. upload an image, reuse a managed Gallery image, or use the current Generate/Image Edit result;
2. choose an image-oriented vectorization mode appropriate for artwork or photography;
3. get useful defaults without opening advanced controls;
4. optionally tune preprocessing, crop, palette, and background handling;
5. download and inspect the final sanitized SVG through the same safe lifecycle already accepted for Text-to-SVG;
6. use Creative photo stylization when Krea Image Edit is available without making Krea a dependency for the rest of Image-to-SVG.

Acceptance requires the local Artwork / Photo Direct / Stylized Preserve paths to work even when no generative provider is available.

## 3. Product placement

Image-to-SVG lives inside the existing **Vector** workspace. Vector gains a top-level source/workflow switch:

```text
Text to SVG | Image to SVG
```

Text-to-SVG keeps its accepted controls and behavior unchanged.

Image-to-SVG uses the same result canvas, SVG metadata, Download SVG, View source, Reuse and Delete actions.

## 4. Source contract

Image-to-SVG v1 supports three source kinds:

### 4.1 Upload

The user selects a local raster file. StableAMD must use the existing managed image-upload mechanism where possible rather than introducing an unrelated file transport.

Uploaded data is decoded as an image before processing. The backend must reject malformed or unsupported input and must never trust a browser-supplied filesystem path.

### 4.2 Gallery

A raster Gallery record can be sent to Image-to-SVG through a `Convert to SVG` / Vector reuse action. The backend resolves only a managed history-owned raster path.

SVG Gallery records are not valid raster sources for this flow.

### 4.3 Current image

The current successful result from Generate or Image Edit can be handed to Image-to-SVG without a manual download/re-upload cycle.

The handoff uses the current managed result record/path already known by StableAMD. It must not accept an arbitrary local path from frontend state.

### 4.4 Ownership

Source ownership is explicit:

- uploaded source copies owned exclusively by an Image-to-SVG job may be recorded as owned intermediates;
- Gallery/current sources are references and are never deleted when the SVG record is deleted;
- final SVG, SVG preview, and Image-to-SVG-owned temporary/intermediate files follow the existing managed Vector deletion rules.

## 5. Modes

The primary mode control exposes:

```text
Artwork
Photo / Direct
Photo / Stylized
```

When `Photo / Stylized` is selected, a second control exposes:

```text
Preserve
Creative
```

### 5.1 Artwork

For logos, icons, flat illustrations, pixel art and already-stylized raster artwork.

Goals:

- preserve existing alpha;
- preserve hard edges and flat color regions;
- avoid unnecessary generative or photographic cleanup;
- minimize shape fragmentation;
- favor faithful vectorization over reinterpretation.

Pipeline:

```text
source -> crop -> artwork preprocessing -> optional background removal -> VTracer -> sanitizer -> preview
```

### 5.2 Photo / Direct

For ordinary photographs when the user wants a direct posterized/vectorized interpretation.

Goals:

- deterministic local execution;
- mild denoise and edge-preserving simplification;
- palette reduction when requested;
- no semantic or compositional changes.

Pipeline:

```text
source -> crop -> photo normalization -> direct simplification -> optional background removal -> VTracer -> sanitizer -> preview
```

### 5.3 Photo / Stylized / Preserve

A stronger deterministic local stylization that still preserves the source composition and objects.

Goals:

- flatter color regions than Direct;
- stronger posterization / local simplification;
- preserve identity, pose, object placement and composition because no diffusion model is used;
- produce a cleaner tracing input for photographs with gradients, texture and noise.

Pipeline:

```text
source -> crop -> preserve-first local stylization -> optional background removal -> VTracer -> sanitizer -> preview
```

### 5.4 Photo / Stylized / Creative

An opt-in generative preprocessing path.

The first provider is the already target-accepted **Krea 2 whole-image Image Edit** implementation. The Image-to-SVG contract remains provider-aware so a different provider can be added later without changing the request or Gallery model.

Goals:

- transform a photograph into cleaner flat/vector-like raster art before tracing;
- preserve the broad subject and composition, but explicitly allow a creative reinterpretation;
- never make this path a prerequisite for Artwork, Direct or Preserve.

Pipeline:

```text
source
  -> crop
  -> Krea Image Edit vector-style transformation
  -> release GPU runtime
  -> optional background removal / final local simplification
  -> VTracer
  -> sanitizer
  -> preview
```

If Krea Image Edit is unavailable, only Creative is disabled. The other Image-to-SVG modes remain fully usable.

## 6. Main controls

The default Image-to-SVG form stays short:

- Source;
- Mode;
- Stylization (`Preserve` / `Creative`) only when relevant;
- Detail: `Simple | Medium | Detailed`;
- Colors: `Auto | 2 | 4 | 8 | 16`;
- Background: `Preserve | Transparent`;
- Crop: `Preserve canvas | Auto-trim | Manual crop`;
- Convert to SVG.

`Preserve` is the default for both canvas and background.

Existing source alpha is preserved unless the user explicitly requests background removal or a preprocessing operation necessarily changes it.

## 7. Advanced controls

Advanced controls are available but collapsed by default.

The normalized product-level controls are:

- `Smoothing`: 0..100;
- `Edge strength`: 0..100;
- `Denoise`: 0..100;
- `Posterize`: 0..100;
- `Background tolerance`: 0..255, shown when transparent/background removal is active.

Mode-specific defaults map these normalized controls to concrete Pillow/VTracer preprocessing settings. The frontend does not expose implementation-specific filter names.

Recommended v1 defaults:

| Mode | Smoothing | Edge | Denoise | Posterize |
| --- | ---: | ---: | ---: | ---: |
| Artwork | 20 | 70 | 10 | 20 |
| Photo / Direct | 35 | 55 | 35 | 45 |
| Photo / Stylized / Preserve | 55 | 65 | 50 | 70 |
| Photo / Stylized / Creative | 30 | 60 | 20 | 35 |

Reset restores the active mode preset.

## 8. Crop behavior

### Preserve canvas

No crop. Original aspect ratio and full decoded canvas are retained.

### Auto-trim

StableAMD identifies removable exterior margin from existing alpha or border-connected near-background regions and trims only the exterior bounding area. It must not globally remove a matching color from the interior of the subject.

If no safe exterior margin is found, Auto-trim leaves the canvas unchanged.

### Manual crop

The frontend provides a simple crop rectangle over the source preview. The backend receives crop coordinates tied to the decoded source dimensions and validates that:

- x/y are non-negative;
- width/height are positive;
- the crop is fully inside the source image;
- stale dimensions cannot silently crop a different source revision.

Cropping happens before stylization/vectorization.

## 9. Background behavior

### Preserve

This is the default. Existing RGB/alpha content is preserved.

### Transparent

StableAMD removes only border-connected background regions. The accepted Text-to-SVG flood-fill semantics are reused/generalized rather than introducing a global color delete.

If the source already contains useful alpha, existing transparent pixels remain transparent and participate in background inference safely.

`Background tolerance` controls near-background matching. The default remains conservative (`18`) unless mode-specific physical testing proves another value is safer.

## 10. Preprocessing implementation direction

Local modes should use lazy-loaded Pillow/NumPy operations already compatible with the StableAMD runtime. Do not add OpenCV or another heavy dependency for v1 unless implementation evidence shows the accepted runtime cannot produce the required behavior.

The local pipeline should be composed from deterministic primitives such as:

- RGBA normalization;
- EXIF orientation normalization where applicable;
- bounded resize only when required by complexity/performance limits;
- median/edge-preserving denoise;
- palette quantization/posterization;
- restrained sharpen/edge enhancement;
- alpha-preserving composition;
- border-connected background analysis.

The exact primitive mapping belongs in code/tests, not in frontend vocabulary.

## 11. Request contract

The backend gets a dedicated Image-to-SVG request validator. It must reject unknown fields instead of silently accepting them.

Conceptual request shape:

```json
{
  "source": {
    "kind": "upload | gallery | current",
    "id": "managed-source-identifier"
  },
  "mode": "artwork | photo-direct | photo-stylized",
  "stylization": "preserve | creative",
  "detail": "simple | medium | detailed",
  "colors": "auto | 2 | 4 | 8 | 16",
  "background": "preserve | transparent",
  "cropMode": "preserve | auto | manual",
  "crop": {"x": 0, "y": 0, "width": 1, "height": 1},
  "advanced": {
    "smoothing": 0,
    "edgeStrength": 0,
    "denoise": 0,
    "posterize": 0,
    "backgroundTolerance": 18
  }
}
```

Rules:

- `stylization` is valid only for `photo-stylized`;
- `crop` is valid only for `cropMode=manual`;
- source identifiers resolve server-side to managed assets;
- Creative is rejected with a clear capability error when no supported Creative provider is ready;
- local modes do not require Krea or Z-Image.

## 12. Creative provider contract

Creative preprocessing uses a provider adapter rather than directly embedding Krea-specific assumptions in the generic Image-to-SVG pipeline.

The adapter contract is conceptually:

```text
stylize_for_vector(source, settings) -> managed raster result
```

Krea 2 Image Edit is the v1 implementation.

The server-owned Krea instruction should request a clean flat vector-like rendering with solid regions, restrained texture, clear edges, no newly invented text/watermarks, and composition preservation. Detail/color settings can influence that instruction.

The user is not exposed to Krea sampler/scheduler/LoRA/ControlNet controls from Image-to-SVG v1.

## 13. Job and runtime behavior

Image-to-SVG reuses the generic async job transport and reports `jobKind=vector` with an Image-to-SVG subtype.

Local Artwork / Direct / Preserve jobs do not require a GPU generation lock. They should use a Vector-local serialization guard for tracing/history writes so expensive VTracer work does not race itself unnecessarily.

Creative acquires the existing shared generation/GPU lock only for the Krea Image Edit stage. After the raster result exists, StableAMD releases the Krea runtime and performs preprocessing/VTracer/sanitizer/preview locally.

A Creative failure after Krea produced a usable raster keeps that raster traceable/visible according to existing failure-evidence semantics rather than deleting evidence prematurely.

## 14. Vectorization and sanitizer

The accepted components are reused unchanged wherever possible:

- pinned VTracer `1.0.0-alpha.4`;
- `resvg_py==0.5.0` preview renderer;
- current Clean SVG allow-list sanitizer and complexity limits;
- safe `/api/vector/source` JSON source retrieval;
- Blob-based download;
- ownership-aware deletion.

Image-to-SVG must not weaken the sanitizer to accommodate input complexity.

If a trace exceeds existing Clean SVG path/node/file limits, the job fails with an actionable message suggesting lower Detail, fewer Colors or stronger simplification.

## 15. Result and history metadata

Image-to-SVG records remain `assetType=svg` and include the existing SVG lifecycle fields plus:

- `workflow: image-to-svg-v1`;
- `sourceKind`;
- source record identifier/path in managed internal metadata;
- source width/height;
- final crop rectangle / crop mode;
- `mode`;
- `stylization` when applicable;
- `detail`;
- `colors`;
- `background`;
- advanced normalized settings;
- Creative provider/model when used;
- preprocessing duration;
- Creative generation duration when used;
- vectorization duration;
- path count / node count;
- final SVG/preview paths;
- `sanitized=true`.

History records must clearly distinguish Text-to-SVG from Image-to-SVG while both render as SVG Vector cards.

## 16. Gallery and handoff UX

Raster Gallery cards gain a **Convert to SVG** action. It opens Vector -> Image-to-SVG with that managed raster selected.

The current Generate/Image Edit result gains an equivalent **Convert to SVG** handoff where the current-result action surface is available.

Image-to-SVG SVG cards keep:

- Download SVG;
- View source;
- Reuse;
- Delete.

Reuse restores the Image-to-SVG workflow/mode/settings and source reference when the original managed source still exists. If the source was removed, settings still restore but the UI asks for/selects a new source rather than failing silently.

## 17. Failure handling

Errors are stage-specific:

- source unavailable/invalid;
- crop invalid/stale;
- Creative provider unavailable;
- Creative generation failed;
- preprocessing failed;
- vectorizer failed;
- sanitizer/complexity rejected;
- preview failed;
- history persistence failed.

The frontend shows the stage message without exposing an unsafe raw filesystem path.

Persistence order follows the accepted Vector rule: do not hide/delete useful intermediates until the final SVG history record is safely persisted.

## 18. Security boundaries

Image-to-SVG must preserve the existing Vector threat model:

- no arbitrary browser-supplied filesystem paths;
- no raw unsanitized SVG served as a navigable document;
- no script/image/text/href/event/DTD/entity/unknown-namespace relaxation;
- upload and Gallery/current source resolution stays within managed roots/history ownership;
- manual crop and advanced numeric inputs are strictly bounded;
- malformed images fail before VTracer;
- source metadata is not trusted to allocate unbounded memory.

## 19. Testing strategy

Development follows RED -> GREEN.

Required automated coverage includes:

1. request validation and unknown-field rejection;
2. source resolution for upload/Gallery/current and arbitrary-path refusal;
3. alpha preservation;
4. crop validation and Auto-trim behavior;
5. border-connected transparent background behavior;
6. deterministic Artwork / Direct / Preserve preprocessing fixtures;
7. mode presets and Advanced bounds;
8. Creative capability gating;
9. Creative Krea adapter orchestration and GPU release before tracing;
10. VTracer/sanitizer/preview reuse;
11. complexity failure guidance;
12. history metadata and ownership-aware cleanup;
13. Gallery/current `Convert to SVG` handoff;
14. Image-to-SVG Reuse behavior when source exists and when it is missing;
15. frontend visibility/progressive disclosure and responsive layout;
16. package/import regressions, including no new eager heavy imports.

## 20. Physical RX 6950 XT acceptance

The target worksheet must cover at least:

1. transparent PNG logo/artwork -> Artwork;
2. opaque flat illustration -> Artwork with Auto-trim/background removal;
3. normal photograph -> Photo Direct;
4. same photograph -> Stylized Preserve;
5. same photograph -> Stylized Creative through Krea;
6. manual crop;
7. local mode with Krea unavailable;
8. Gallery handoff;
9. current Generate/Image Edit handoff;
10. Download/View source/Reuse/Delete;
11. ordinary Krea and Z-Image generation after Creative/vector work;
12. repeated Image-to-SVG run without runtime/VRAM degradation.

Image-to-SVG is not target-accepted until those checks pass on the RX 6950 XT.

## 21. Explicit non-goals for v1

- semantic/native vector model generation;
- OCR or guaranteed text fidelity;
- editable semantic layers/groups named by object;
- gradients, masks, filters, embedded rasters or other Rich SVG features;
- arbitrary Creative provider selector in the UI;
- Image-to-SVG-specific LoRA/ControlNet/sampler/scheduler controls;
- weakening Clean SVG security/complexity limits;
- infographic/diagram generation (separate phase).

Existing source lettering may be traced as path geometry in Direct/local modes, but v1 does not promise typographic fidelity.

## 22. Implementation boundaries

Prefer extending the current Vector subsystem with focused modules rather than inflating `stableamd_v03_vector.py` into a mixed text/image monolith.

Expected separation:

- Image-to-SVG request/source/preprocess module;
- optional Creative provider adapter;
- shared VTracer/sanitizer/preview/assets modules remain common;
- Vector API gains Image-to-SVG endpoints without changing accepted Text-to-SVG request semantics;
- `app-vector.js`/Vector UI gains the Image-to-SVG workflow and handoff hooks while retaining one Vector product surface.

No unrelated refactoring is part of this phase.
