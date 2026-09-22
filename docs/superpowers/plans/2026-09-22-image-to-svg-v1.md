# StableAMD Image-to-SVG v1 Implementation Plan

Date: 2026-09-22
Design: docs/superpowers/specs/2026-09-22-image-to-svg-v1-design.md
Target: feat/stableamd-v0.3 / PR #4

## Execution rules
- TDD: RED -> GREEN for each behavior.
- Reuse the accepted Text-to-SVG VTracer, sanitizer, preview, Vector Gallery lifecycle.
- Do not weaken Clean SVG security/complexity rules.
- Local modes must work without Krea/Z-Image.
- Creative alone may require Krea.
- Keep PR #4 draft until physical RX 6950 XT acceptance.

## Task 1 — source resolution and request contract
Add a dedicated Image-to-SVG validator and managed source resolver for upload/gallery/current sources. Reuse existing managed image ownership/history rules. Reject arbitrary filesystem paths, malformed sources, unknown fields, invalid crop/advanced values and invalid mode combinations.
Tests first.

## Task 2 — deterministic preprocessing
Implement normalized image decoding, EXIF orientation, crop modes, alpha preservation, auto-trim, border-connected background removal, and deterministic Artwork/Photo Direct/Preserve preprocessing using Pillow/NumPy only. Add mode presets and complexity-safe resizing where needed.
Tests first with small fixtures.

## Task 3 — async Image-to-SVG orchestration
Add image-to-svg subtype to the vector job path. Local modes use a vector-local serialization guard; Creative acquires the existing GPU/generation lock only for Krea, then releases runtime before VTracer. Reuse existing VTracer/sanitizer/preview/persistence and failure-evidence semantics.
Tests first.

## Task 4 — Creative provider adapter
Define provider-neutral stylize_for_vector contract and implement Krea whole-image Image Edit adapter. Add capability gating and explicit failure when Krea is unavailable. Do not expose Krea sampler/LoRA/control knobs.
Tests first.

## Task 5 — result/history metadata and lifecycle
Extend SVG records with workflow/source/mode/crop/advanced/timing/source dimensions/provider metadata. Ensure source ownership is safe: deleting an Image-to-SVG SVG never deletes Gallery/current sources. Reuse restores settings and source when available, otherwise requests a replacement.
Tests first.

## Task 6 — upload + Gallery/current handoff APIs
Wire local upload through the existing managed upload mechanism. Add raster Gallery Convert-to-SVG and current Generate/Image Edit handoff APIs/actions. Keep server-side source resolution authoritative.
Tests first.

## Task 7 — Vector workspace UI
Add Text to SVG / Image to SVG switch. Build compact source/mode controls, stylization selector, crop controls, Advanced disclosure, source preview/crop UI, job progress/error states, and reuse state. Preserve existing Text-to-SVG behavior unchanged.
Tests first; responsive Pester coverage.

## Task 8 — Gallery integration
Add Convert to SVG action to raster cards, SVG metadata distinction, Image-to-SVG reuse behavior, and safe deletion. Verify current-result handoff without download/re-upload.
Tests first.

## Task 9 — packaging/import/CI
Update package inclusion and isolated-import tests. Run full Python/Pester/package CI at exact head. Fix only evidence-backed failures.

## Task 10 — physical RX 6950 XT acceptance
Run the worksheet:
1 transparent PNG artwork;
2 opaque flat artwork with auto-trim/background removal;
3 normal photo Direct;
4 same photo Stylized Preserve;
5 same photo Stylized Creative/Krea;
6 manual crop;
7 local mode with Krea unavailable;
8 Gallery handoff;
9 current Generate/Image Edit handoff;
10 Download/View source/Reuse/Delete;
11 ordinary Krea/Z-Image after Creative;
12 repeated run stability.
Do not mark accepted until all required checks pass.

## Non-goals
No semantic/native vector generation, OCR guarantees, raw SVG serving, sanitizer relaxation, SDXL-specific controls, new heavy dependencies without evidence, or unrelated Character Sheet changes.
