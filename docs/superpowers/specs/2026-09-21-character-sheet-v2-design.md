# StableAMD Character Sheet v2 — Identity Edit design

Date: 2026-09-21
Branch: `feat/stableamd-v0.3`
Status: design for review

## Intent

Character Sheet v2 replaces prompt-only identity preservation with the Krea 2 Identity Edit training path used by the community workflow referenced by the user. The success criterion is not merely a visually similar character: the same person/character should remain recognizable across the sheet, while the noisy/ghosted reference artifacts seen in the current sequential Character Sheet are substantially reduced.

The physical target remains Windows + Radeon RX 6950 XT 16 GiB (`gfx1030`). Existing accepted Krea 2 txt2img, Image Edit, OpenPose, Depth and user-LoRA routes must not regress.

## Evidence and reference workflow

Reference implementation:
- Reddit: `https://www.reddit.com/r/comfyui/comments/1w6o357/krea_2_character_sheets_flux_2_klein_detailer/`
- Workflow repo: `https://github.com/sempersatirica/comfy-workflows/tree/main/Krea2/character-sheet`
- Identity model: `https://huggingface.co/conradlocke/krea2-identity-edit`
- Required nodes: `https://github.com/lbouaraba/comfyui-krea2edit`

Important properties of the reference workflow:
- `krea2_identity_edit_v1_2.safetensors` at strength `1.0`;
- Turbo-style generation at CFG `1`;
- approximately `10` steps is the quality/identity balance recommended by the model author;
- Krea2Edit dual conditioning is required: source latent tokens plus image-grounded Qwen3-VL encoding;
- v1.2 `fit` geometry handles source/output aspect mismatch;
- `ref_boost` around `4` is the documented strong-likeness starting point;
- higher `grounding_px` favors identity; `1024` is appropriate for people;
- output should remain at or below approximately 2 MP;
- `target_latent` should be wired so source pre-encoding happens before sampling and does not fragment/offload the sampler mid-run.

The current StableAMD Character Sheet does **not** use this training-matched path. It uses the older Ostris reference-conditioning route plus crop/prompt/anchor heuristics, which physical testing showed can preserve broad appearance while changing the actual person.

## Product decision

### v2 becomes the default Character Sheet path

The UI keeps the user-facing name **Character sheet**. When the v2 dependencies are ready, it uses the Identity Edit v1.2 route. The current five-job/sequential implementation remains backend-compatible as `legacy-sequential` during the v0.3 acceptance period but is not the default product path.

This is intentionally different from v1. The v2 priority is likeness and clean output, not preserving the existing orchestration for its own sake.

## Generation architecture

### Stage A — one Identity Edit character-sheet render

Generate one sheet with five ordered panels in a single Krea job:

1. FACE close-up
2. FRONT full body
3. 3/4 full body
4. SIDE full body
5. BACK full body

Default target: `1792 x 1024` (1.84 MP, divisible by 16, below the documented 2 MP ceiling).

The source image is passed through the v1.2 Krea2Edit pixel path using `fit_mode=fit`; StableAMD no longer needs to expand/crop the source to the output ratio merely to satisfy reference geometry.

Provider recipe:
- existing Krea 2 Turbo FP8 bundle;
- `LoraLoaderModelOnly(krea2_identity_edit_v1_2.safetensors, strength=1.0)`;
- `Krea2EditModelPatch` with source latent + VAE + raw source image + target latent;
- `fit_mode=fit`;
- `ref_boost=4.0`;
- `Krea2EditGroundedEncode` with the same source image;
- `grounding_px=1024`;
- `EmptySD3LatentImage(1792, 1024)` wired both to `KSampler.latent_image` and `Krea2EditModelPatch.target_latent`;
- `10 steps / CFG 1 / Euler / simple / denoise 1`;
- negative conditioning remains the normal CFG-1 fast path.

The base prompt is modeled on the community workflow but retains StableAMD's five requested views. A short editable **Character description** is appended after the sheet instruction, as recommended by the reference workflow.

### Stage B — local panel extraction

The base sheet is split into five deterministic horizontal panel regions. The base image remains intact as a hidden intermediate asset.

Each panel is stored internally with a role (`face`, `front`, `three-quarter`, `side`, `back`) so the detailer can apply view-specific rules. Panel extraction is local/Pillow work; it is not another diffusion pass.

### Stage C — face identity detailer

For `FACE`, `FRONT`, `3/4`, and `SIDE`:

1. run DWPose on that panel independently;
2. obtain a face/head box;
3. expand the box to include enough hair/head context;
4. crop the generated panel around that region;
5. run a second Krea2Edit job using two-input conditioning:
   - image 1 = generated panel face/head crop (scene/composition to preserve),
   - image 2 = original tight face/head crop from the source (identity authority);
6. use `fit_mode=fit`, identity LoRA `1.0`, `ref_boost` strong-likeness settings and view-specific wording that forbids changing the camera angle;
7. feather-stitch the refined crop back into the original panel.

`BACK` skips face detailing by design.

Detailer failure is non-fatal. If no valid face is detected or a detailer child fails, StableAMD keeps the clean base panel and records `detailerSkipped=true` for that panel instead of discarding the whole sheet.

### Stage D — final composite

Reassemble the five final panels into the persisted sheet, with labels outside generated pixels. The final sheet is the only default Gallery card.

The base full sheet, extracted panels and detailer intermediates remain linked in metadata and hidden from the normal Gallery so debugging is still possible without flooding the UI.

## Dependency architecture

### ComfyUI node pack

Add a separate pinned dependency for `lbouaraba/comfyui-krea2edit` at commit:

`86f886dac23013d88996e3a2e99093ba44d322fb`

The node pack has no extra Python package requirements. It coexists with the currently accepted Ostris integration; normal Krea Image Edit is not migrated in this change.

Required node availability for v2:
- `Krea2EditModelPatch`
- `Krea2EditGroundedEncode`

### Identity LoRA

Primary quality dependency:

`conradlocke/krea2-identity-edit/krea2_identity_edit_v1_2.safetensors`

Default strength: `1.0`.

The full-rank v1.2 file is the first physical acceptance target because it matches the referenced workflow. StableAMD may later expose the documented `r128`/`r64` low-VRAM variants, but v2 acceptance must not silently substitute one before comparison on the RX 6950 XT.

The curated installer must use the same strict behavior as existing managed dependencies: allow-listed HTTPS source, pinned identity, expected size/hash, temporary download and atomic promotion, no silent overwrite.

## Backend organization

Introduce a dedicated provider layer rather than further expanding the legacy character-sheet file:

- `app/backend/stableamd_v03_krea_identity_edit.py`
  - dependency readiness;
  - Identity Edit graph injection;
  - one-input and two-input edit contexts;
  - v1.2 settings (`fit_mode`, `ref_boost`, `grounding_px`, target latent);
- `app/backend/stableamd_v03_character_sheet_v2.py`
  - base sheet orchestration;
  - panel extraction;
  - per-panel DWPose face detailer orchestration;
  - feather stitch;
  - final history/metadata;
- existing `stableamd_v03_character_sheet.py`
  - retained as legacy sequential path until v2 target acceptance.

The final bridge MRO wires v2 before the legacy sheet mixin, while all non-character-sheet requests continue to delegate unchanged.

## API contract

The public task remains `editTask="character-sheet"`.

New request fields:
- `characterSheetVersion`: `v2` (default when ready) or `legacy-sequential`;
- `characterDescription`: optional short free text;
- `characterSheetDetailer`: boolean, default `true`;
- advanced/internal settings are server-owned for the acceptance gate; users do not initially tune LoRA strength, `ref_boost` or grounding resolution.

Response/history adds:
- `CharacterSheetVersion="v2-identity-edit"`;
- `CharacterSheetIdentityLora`;
- `CharacterSheetIdentityLoraStrength=1.0`;
- `CharacterSheetRefBoost=4.0`;
- `CharacterSheetGroundingPx=1024`;
- `CharacterSheetBaseImagePath`;
- per-panel detailer status;
- final composite path and dimensions.

## UI

Character Sheet panel changes:
- display `Character Sheet v2 · Identity Edit` when dependencies are ready;
- add `Character description` textarea below the identity prompt;
- display dependency state and an Install action when the Identity Edit node pack/LoRA is missing;
- show progress by stage: `Base sheet -> Face detail 1/4 ... -> Final compose`;
- keep the neutral-source-pose recommendation visible;
- hide global Size/Ratio while v2 is active because v2 owns its tested output geometry;
- legacy sequential mode is only exposed under Advanced during the acceptance period.

## Runtime / 16 GiB policy

The current per-job ComfyUI `/free` behavior remains. Run `/free` after the base sheet and after every detailer Krea job.

The v1.2 `target_latent` input is mandatory because the node author's VRAM notes explicitly warn that source VAE encoding during sampling can force partial offload of the sampler and leave the rest of the run streaming weights from CPU.

No parallel Krea jobs are allowed in v2.

## Failure behavior

- missing Identity Edit node pack or LoRA: v2 is unavailable with an actionable dependency message; do not silently fall back and present it as v2;
- base sheet failure: fail the Character Sheet job;
- individual detailer failure: retain the undetailed panel and continue;
- final composition/history failure: keep intermediates visible for diagnosis;
- only after the final v2 asset is safely persisted are intermediates hidden from the default Gallery.

## Testing strategy

TDD gates:

1. dependency catalog/readiness tests for pinned node pack + LoRA;
2. workflow graph tests asserting:
   - Identity LoRA is model-only at `1.0`;
   - `Krea2EditModelPatch` receives source latent, source image/VAE and target latent;
   - `fit_mode=fit` and `ref_boost=4`;
   - grounded encoder receives the source image at `grounding_px=1024`;
   - base sheet is `1792 x 1024`, `10 steps`, CFG `1`, Euler/simple;
3. API validation tests for version/description/detailer fields;
4. panel extraction + stitch tests with synthetic images;
5. detailer fallback tests when DWPose cannot find a face;
6. frontend tests for v2 readiness, install state and staged progress;
7. full existing Python + Pester + package CI;
8. physical RX 6950 XT acceptance with the exact source images that exposed identity drift and visual debris.

## Physical acceptance criteria

Do not mark v2 accepted until all are true on the RX 6950 XT:

- the full base + detailer + final compose run finishes without DynamicVRAM/offload failure;
- the source person remains recognizably the same person in FACE / FRONT / 3/4 / SIDE;
- BACK contains no inserted face/portrait;
- the repeated ghost/grid/debris artifacts visible in v1 are materially reduced;
- a second consecutive run remains stable;
- ordinary Krea Image Edit still works after a complete v2 run;
- Gallery shows one final Character Sheet card by default.

If identity is still insufficient after the training-matched v1.2 route, the next escalation is candidate generation + face-embedding scoring. That is explicitly out of scope for the first v2 implementation so we can measure the effect of the proper Identity Edit conditioning before adding another subsystem.
