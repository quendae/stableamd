# StableAMD Text-to-SVG v1 — clean vector design

Date: 2026-09-21
Branch: `feat/stableamd-v0.3`
Status: design for review

## Intent

Text-to-SVG v1 adds a dedicated vector-generation tool to StableAMD without changing the accepted raster-provider contract. The first release targets two user-facing use cases:

1. icon / logo mark generation without text;
2. general flat vector illustration.

The output must be a real, editable SVG document rather than a raster image wrapped in SVG. The first physical target remains Windows + AMD Radeon RX 6950 XT 16 GiB (`gfx1030`). Existing Z-Image, Krea, Character Sheet, Control, Gallery and upscale behavior must not regress.

Text rendering, wordmarks, diagrams and infographic-specific layout are intentionally deferred. The v1 product is text-free.

## Product decision

### Dedicated Vector tool

Vector generation is exposed as a separate top-level tool instead of another mode inside normal raster `Generate`.

Planned navigation:

```text
Generate
Edit
Control
Vector
  -> Text to SVG
Gallery
```

The Vector workspace owns its own settings and hides raster-only concepts such as sampler, scheduler, LoRA stack and arbitrary image-generation size controls.

### Provider-neutral contract

The product contract is `TextToSvgRequest -> VectorProvider -> SvgResult`.

The first provider is:

```text
zimage-vtrace
```

It uses the already accepted Z-Image Turbo path to create a vector-friendly raster intermediate, then performs local raster-to-vector conversion. This isolates the UI and API from the implementation so a future direct-SVG backend such as OmniSVG can be added without redesigning the product surface.

## v1 scope

### Supported

- icons;
- logo marks / symbols without text;
- flat illustrations;
- transparent or solid backgrounds;
- limited palettes;
- Simple / Medium / Detailed vectorization profiles;
- deterministic seed reuse;
- SVG persistence and PNG preview;
- Gallery reuse/delete;
- managed dependency readiness for the vectorizer.

### Explicitly deferred

- wordmarks;
- readable typography;
- `<text>` / `<tspan>` output;
- infographic-specific composition;
- diagrams with semantic connectors/layout;
- gradients as a product feature;
- SVG filters, masks and clipping workflows;
- embedded raster images;
- arbitrary scripts or external resources;
- direct-SVG foundation models as an acceptance dependency;
- Image-to-SVG, which follows Text-to-SVG after this contract is accepted.

## Generation architecture

The v1 pipeline is:

```text
user prompt
  -> vector prompt builder
  -> existing Z-Image Turbo generation
  -> raster intermediate
  -> release ComfyUI / model runtime memory
  -> VTracer
  -> SVG sanitizer / normalizer
  -> final SVG
  -> PNG preview
  -> Gallery/history persistence
```

The raster intermediate is implementation detail, not the product asset.

### Stage A — vector-oriented raster generation

Reuse the accepted Z-Image Turbo generation route. Do not introduce a new model runtime for v1.

StableAMD appends server-owned vector-style constraints to the user's content prompt. The instruction should emphasize:

- flat vector illustration;
- clean solid shapes;
- crisp boundaries;
- limited palette;
- no text, letters, numbers or watermark;
- no photographic texture;
- no complex lighting;
- no soft depth-of-field effects;
- no realistic material noise;
- no gradients for the initial acceptance profile.

`Icon / Logo mark` adds stricter composition constraints:

- one dominant centered subject or symbol;
- minimal background detail;
- low object count;
- simple silhouette;
- high color separation;
- limited palette.

`Vector Illustration` permits multiple objects and fuller composition while keeping the flat/vector constraints.

No SVG-specific LoRA is required for v1 acceptance. A curated vector-domain LoRA may be evaluated later as an optional quality enhancement only after the baseline provider is accepted.

### Stage B — runtime release

After the raster image exists, release the Z-Image / ComfyUI generation memory before vectorization.

VTracer is CPU-side post-processing and must not hold the Radeon model runtime or reserve VRAM. This separation is part of the 16 GiB stability policy.

### Stage C — vectorization

Use VTracer as the first raster-to-vector backend.

The implementation should invoke a managed CLI binary rather than make StableAMD depend on a Rust build toolchain or a Python extension build on the target machine.

Initial pinned dependency candidate:

```text
repository: visioncortex/vtracer
release:    1.0.0-alpha.4
asset:      vtracer-x86_64-pc-windows-msvc.zip
sha256:     8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531
license:    MIT OR Apache-2.0
```

The exact pinned asset remains server-owned and must use the same strict installer behavior as other managed StableAMD dependencies: allow-listed HTTPS source, expected identity/hash, temporary download, extraction into a managed runtime directory and no silent overwrite of an invalid installation.

### Vectorization profiles

Expose three StableAMD-owned profiles. Exact VTracer flag values are implementation details finalized during the implementation plan and verified against the pinned CLI schema.

#### Simple

Target: icons and logo marks.

Behavior:
- stronger simplification;
- fewer paths;
- stronger color consolidation;
- larger minimum meaningful shape;
- lower edit complexity.

#### Medium

Default general profile.

Behavior:
- balanced curve fitting;
- moderate color consolidation;
- enough detail for flat illustration while remaining editable.

#### Detailed

Target: richer vector illustration.

Behavior:
- less aggressive simplification;
- more retained shapes;
- higher path count accepted;
- still subject to sanitizer and complexity bounds.

The UI labels are stable product concepts; raw VTracer internals are not exposed in v1.

## Clean SVG contract

The final result is constrained to a deliberately small safe subset.

### Allowed elements

- `svg`
- `g`
- `path`
- `rect`
- `circle`
- `ellipse`
- `polygon`
- `polyline`
- `line`

### Allowed presentation/geometry attributes

At minimum:

- `viewBox`
- `width`
- `height`
- `d`
- coordinate attributes required by the allowed geometric elements;
- `fill`
- `stroke`
- `stroke-width`
- `opacity`
- `fill-opacity`
- `stroke-opacity`
- `transform`
- basic line join/cap attributes where produced by the vectorizer.

The sanitizer uses an allow-list, not a remove-known-bad-elements strategy.

### Forbidden in v1

- `script`;
- event-handler attributes;
- `foreignObject`;
- `image`;
- `text` / `tspan`;
- `use` referencing external content;
- external URLs;
- remote stylesheets;
- embedded fonts;
- data-URI raster images;
- filters;
- masks;
- clipping paths;
- animation elements;
- XML entity expansion / DTD-dependent content.

Unknown elements and unsafe attributes fail sanitization rather than being silently trusted.

## SVG sanitizer / normalizer

A dedicated module parses the VTracer output as XML and produces the final asset.

Responsibilities:

1. reject malformed XML;
2. reject prohibited elements, attributes and namespaces;
3. reject embedded/external raster resources;
4. require one root `<svg>`;
5. require a valid finite `viewBox` or derive one only from trusted vector dimensions when unambiguous;
6. remove metadata/comments that have no product value;
7. normalize presentation attributes into the supported clean subset;
8. remove empty groups and obviously empty shapes;
9. reject a document with no drawable vector geometry after normalization;
10. enforce file-size / node-count / path-count complexity limits to prevent pathological Gallery assets;
11. serialize deterministically enough for tests and reuse.

The sanitizer is not expected to perform aggressive artistic path optimization in v1. Quality-preserving normalization is preferred over shrinking the SVG at the cost of shape drift.

## Preview architecture

Every successful SVG asset also receives a PNG preview for the existing Gallery card system.

The preview is derived from the **sanitized final SVG**, not from the Z-Image raster intermediate. This makes preview rendering part of the acceptance check: if the final SVG cannot render correctly, the operation is not successful.

The concrete local renderer is selected during implementation planning based on already shipped runtime capabilities. It must not require a browser automation stack merely to create Gallery thumbnails.

## API contract

Introduce a separate vector API instead of overloading the existing raster `/generate` request.

Primary route:

```text
POST /api/vector/text-to-svg
```

The frontend should use the existing async job transport for the full operation. The vector route may submit through the same `submit -> poll -> result` job infrastructure used by long image generation; it must not invent another job manager.

### Request

Conceptual request shape:

```json
{
  "prompt": "a fox curled around a crescent moon",
  "style": "icon",
  "detail": "medium",
  "colors": 4,
  "background": "transparent",
  "seed": 12345
}
```

Validation:

- `prompt`: required, non-empty, bounded length;
- `style`: `icon` or `illustration`;
- `detail`: `simple`, `medium`, `detailed`;
- `colors`: `auto` or a supported bounded palette count such as `2`, `4`, `8`, `16`;
- `background`: `transparent` or `solid`;
- solid background may carry one validated color value when implemented;
- `seed`: existing StableAMD integer seed semantics.

Text/wordmark generation is not advertised. The server-owned prompt always forbids textual content. Obvious dedicated wordmark/text-only modes are not added in v1 rather than attempting broad natural-language censorship of every prompt containing a textual concept.

### Response/history

Conceptual result fields:

```json
{
  "assetType": "svg",
  "provider": "zimage-vtrace",
  "svgPath": "...",
  "previewPath": "...png",
  "width": 1024,
  "height": 1024,
  "pathCount": 37,
  "sanitized": true,
  "seed": 12345
}
```

History additionally records:

- original user prompt;
- effective vector prompt/version;
- style;
- detail profile;
- palette setting;
- background setting;
- seed;
- provider id;
- vectorizer dependency/version;
- sanitizer contract/version;
- SVG path;
- preview path;
- hidden raster-intermediate relationship where retained for diagnostics;
- generation, vectorization and total elapsed time.

## Asset serving

SVG is a new asset type and should not be forced through an image-only endpoint that assumes PNG/JPEG semantics.

Introduce a safe managed-output route for vector assets. It must:

- resolve only files under StableAMD-managed output roots;
- permit `.svg` only for the SVG endpoint;
- use a safe content type;
- prevent arbitrary filesystem paths;
- support download/open-source behavior without evaluating untrusted external content.

Because every persisted SVG is sanitized before storage, the asset route never intentionally serves raw unsanitized vectorizer output as the product asset.

## Gallery integration

Gallery receives `assetType="svg"` support.

A vector card displays the sanitized SVG's PNG preview and a visible SVG/vector badge. Actions:

- open / preview;
- download SVG;
- view source;
- reuse settings;
- regenerate;
- delete.

`Reuse` restores prompt, style, detail, colors, background and seed into the Vector workspace.

`Delete` removes the final SVG, PNG preview, history record and managed hidden intermediates owned by that result according to the existing Gallery deletion safety model.

The Z-Image raster intermediate should not appear as a normal Gallery card after successful vector persistence. It may remain traceable through history metadata for diagnosis.

## Frontend

Add a focused Vector workspace rather than extending the already dense Generate controls.

Initial controls:

```text
Prompt
Style       Icon / Logo mark | Vector Illustration
Detail      Simple | Medium | Detailed
Colors      Auto | 2 | 4 | 8 | 16
Background  Transparent | Solid
Seed
Generate SVG
```

The result area renders the safe final SVG or its preview and exposes vector-specific actions.

Raster-only controls are absent from this workspace:

- sampler;
- scheduler;
- LoRA stack;
- Image Edit controls;
- ControlNet controls;
- arbitrary denoise;
- Character Sheet controls.

Dependency state is visible. If VTracer is missing/invalid, generation is unavailable with an `Install Vectorizer` action and an actionable status. There is no fallback that returns PNG while claiming SVG success.

## Backend organization

Prefer small focused modules:

- `app/backend/stableamd_v03_vector.py`
  - vector API validation;
  - provider contract;
  - Text-to-SVG orchestration;
  - persistence/history integration;
  - dependency/status endpoints;
- `app/backend/stableamd_v03_svg_vectorizer.py`
  - VTracer managed dependency;
  - profile -> CLI arguments mapping;
  - vectorizer process execution;
  - temporary file lifecycle;
- `app/backend/stableamd_v03_svg_sanitize.py`
  - XML parsing;
  - safe allow-list;
  - normalization;
  - complexity accounting;
  - deterministic serialization;
- frontend module such as `app/frontend/app-vector.js`
  - Vector workspace state;
  - dependency UX;
  - async submission/progress/result;
  - Gallery reuse handoff.

The final v0.3 server composes the Vector API/bridge as a thin additional layer. Existing provider request behavior delegates unchanged.

Do not place sanitizer, VTracer process management or UI-specific mapping into `stableamd_v03_edit_server.py`.

## Dependency management

VTracer follows the curated dependency pattern rather than ambient PATH discovery.

Readiness states should distinguish at least:

- `ready`;
- `missing`;
- `invalid`;
- `install-required` / equivalent actionable state.

The installer must not require admin privileges, Rust, Cargo or a system-wide Python package.

Install into a StableAMD-managed private runtime directory. Validate the expected executable after extraction before reporting ready.

## Error handling

Failures are stage-specific and must remain actionable:

- raster generation failure -> fail job as Z-Image generation error;
- vectorizer missing -> dependency error before raster generation where possible;
- vectorizer non-zero exit / timeout -> vectorization error; do not publish PNG as SVG success;
- malformed SVG -> sanitization error;
- unsafe SVG -> sanitization error with internal diagnostics;
- empty SVG after sanitation -> quality/validation error;
- preview render failure -> finalization failure;
- history persistence failure -> keep generated assets available for diagnosis rather than falsely reporting fully persisted success.

Temporary raw SVG from the vectorizer is never promoted to the Gallery as final when sanitization fails.

## Testing strategy

Implementation uses TDD.

### Backend/API tests

1. vector route accepts only the supported request contract;
2. prompt/style/detail/palette/background/seed validation;
3. vector route uses the accepted Z-Image provider rather than creating a second raster generator;
4. vector workflow releases generation runtime before CPU vectorization;
5. provider result records `zimage-vtrace`;
6. vectorizer missing/invalid states are actionable;
7. installer rejects wrong hash / wrong asset and never promotes partial installs;
8. Simple / Medium / Detailed map to stable internal vectorizer profiles.

### Sanitizer security/validity tests

Fixtures must cover:

- valid path-only SVG;
- malformed XML;
- `<script>`;
- event attributes such as `onclick`;
- `<foreignObject>`;
- `<image>`;
- `<text>` / `<tspan>`;
- external URL references;
- data URI raster content;
- filters/masks/clips;
- unknown namespace/element;
- invalid/non-finite `viewBox`;
- empty document;
- excessive node/path complexity;
- deterministic normalized output for a stable fixture.

### Asset/Gallery tests

1. final SVG and preview paths are persisted together;
2. preview is associated with `assetType=svg`;
3. SVG download endpoint rejects paths outside managed output;
4. reuse restores vector settings rather than raster Generate settings;
5. delete removes SVG + preview + owned hidden intermediate safely;
6. successful raster intermediate is hidden from normal Gallery;
7. failed finalization leaves enough trace data for diagnosis.

### Frontend tests

1. Vector navigation/workspace exists;
2. raster-only controls are not shown in Vector workspace;
3. dependency missing state exposes install action;
4. Text-to-SVG uses async submit/poll/result transport;
5. icon vs illustration settings serialize correctly;
6. result actions include SVG download/source and reuse;
7. Gallery renders SVG cards via preview safely.

### Regression/packaging tests

- full existing Python regression suite;
- existing Pester tests;
- package build;
- packaging asserts new backend/frontend modules are present;
- direct v0.3 server import must not eagerly require optional preview/vector packages before their tool is invoked;
- existing Z-Image and Krea routes remain unchanged.

## Physical acceptance on RX 6950 XT

Use at least four prompts:

1. two-color simple icon;
2. logo mark / symbol without text;
3. 4-8 color flat illustration;
4. more detailed vector illustration.

For each result verify:

```text
[ ] Z-Image raster stage completes on the accepted AMD path
[ ] runtime is released before vectorization
[ ] VTracer completes without GPU/NVIDIA dependency
[ ] final file is valid SVG/XML
[ ] no raster image is embedded
[ ] no forbidden element/resource survives
[ ] SVG opens in a normal browser
[ ] SVG remains editable as vector paths/shapes
[ ] PNG preview visually corresponds to the final sanitized SVG
[ ] Gallery shows one vector result card, not the raster intermediate
[ ] Reuse restores the Vector settings
[ ] Delete removes managed result assets safely
[ ] normal Z-Image generation still works immediately afterwards
[ ] normal Krea generation still works immediately afterwards
```

Quality acceptance is use-case specific:

- icon/logo mark: clean silhouette, limited palette, manageable path count and no accidental text;
- illustration: recognizable requested composition, clean color regions and useful editability rather than merely high path fidelity to raster noise.

## Security acceptance

SVG is active document content, so sanitizer safety is a release gate rather than polish.

Do not ship direct raw VTracer output to Gallery/download without the sanitizer. Do not rely on browser CSP alone. The persisted product SVG must already satisfy the StableAMD clean-SVG allow-list.

## Future extension points

The architecture deliberately leaves room for:

- `image-to-svg` using the same vectorizer/sanitizer/result contract;
- optional SVG-specialized Z-Image LoRA;
- gradient-capable clean SVG v2;
- infographic/diagram tooling with a separate layout/text contract;
- direct-SVG providers such as OmniSVG behind the same `VectorProvider` result contract.

A future provider that produces SVG directly still passes through the same sanitizer, preview and Gallery pipeline.

## Non-goals for this implementation

- no Character Sheet changes;
- no Krea Image Edit changes;
- no new ControlNet route;
- no direct-SVG model acceptance work;
- no text/wordmark generation;
- no Image-to-SVG in the first implementation wave;
- no arbitrary SVG JavaScript or externally loaded resources;
- no attempt to expose all VTracer tuning knobs in the UI.

## References verified for this design

- StableAMD current v0.3 roadmap and provider/runtime contracts in this repository;
- `visioncortex/vtracer`, which provides raster-to-SVG conversion, a CLI and Python bindings;
- VTracer release `1.0.0-alpha.4`, including an x86_64 Windows MSVC CLI archive;
- VTracer crate licensing declared as `MIT OR Apache-2.0`.

The implementation plan must re-check any external dependency identity/hash before writing installer production code if the pinned release changes.