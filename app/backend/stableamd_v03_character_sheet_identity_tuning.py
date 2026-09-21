from __future__ import annotations

from typing import Any

import stableamd_v03_character_sheet_v2 as sheetv2

base = sheetv2.base


_BASE_IDENTITY_PROMPT = (
    "Create one clean character sheet of the exact same person or character from the references on a plain neutral "
    "grey studio background. Reference A is the full source and controls body proportions, clothing, accessories, "
    "colors and materials. When a second reference is present, the second reference is an authoritative face/head "
    "identity crop and has priority for every visible face. Use five clearly separated panels from left to right: "
    "(1) close-up face portrait looking toward camera, (2) full-body front view, (3) full-body three-quarter view, "
    "(4) full-body strict side profile, (5) full-body back view. Preserve the exact facial geometry and age impression: "
    "face outline, eye spacing and eye shape, eyelids, eyebrows, nose bridge and nose tip, mouth and lip shape, cheek "
    "proportions, jaw and chin, ears, hairline, hairstyle, skin texture and natural asymmetries. Do not beautify, "
    "idealize, symmetrize, age up, age down, make the face more doll-like or model-like, or replace distinctive features "
    "with a generic attractive face. Preserve the source person's real proportions and characteristic expression cues. "
    "Do not add props, duplicate people, inset portraits, text, borders, scenery remnants, ghost anatomy or texture debris."
)

_DETAIL_IDENTITY_PROMPT = (
    "Correct only identity and fine facial/head details in image A so the person matches image B exactly. Image B is "
    "the authoritative original face/head identity reference. Preserve image A's exact camera angle, head orientation, "
    "body pose, clothing, background, lighting and composition. Match the original face outline, eye spacing and eye "
    "shape, eyelids, eyebrows, nose bridge and nose tip, mouth and lip shape, cheek proportions, jaw and chin, ears, "
    "hairline, hairstyle, skin texture, age impression and natural asymmetries. Do not beautify, idealize, symmetrize, "
    "age up, age down, make the face more doll-like or model-like, or replace distinctive features with a generic face. "
    "Do not add another face, portrait inset, accessories, props or background objects. Remove malformed facial texture, "
    "duplicate features, ghost details and noisy artifacts inside the edited head region."
)


class CharacterSheetV2IdentityTuningBridgeMixin:
    """Identity-fidelity layer for Character Sheet v2.

    The accepted v2 pipeline already uses the original face crop as the second
    reference for per-panel detail correction. This layer brings that same
    authoritative face anchor into the BASE sheet generation, where it matters
    most: all five views start from the correct identity instead of asking the
    detailer to repair a generic interpretation afterwards.
    """

    @staticmethod
    def _character_sheet_v2_prompt(description: Any = "") -> str:
        text = str(description or "").strip()
        return f"{_BASE_IDENTITY_PROMPT} Character description: {text}" if text else _BASE_IDENTITY_PROMPT

    @staticmethod
    def _character_sheet_v2_detail_prompt(role: str) -> str:
        if str(role or "").strip().lower() == "side":
            return (
                _DETAIL_IDENTITY_PROMPT
                + " Preserve the current strict side profile exactly; do not rotate the face toward camera."
            )
        return _DETAIL_IDENTITY_PROMPT

    def _generate_krea_identity_edit(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        *,
        image_name: str,
        prompt: str,
        width: int,
        height: int,
        identity_image_name: str | None = None,
    ) -> dict[str, Any]:
        # Detailer calls already provide image B explicitly. Do not replace or
        # restage that reference; only the base pass arrives without image B.
        if identity_image_name:
            return super()._generate_krea_identity_edit(
                request,
                model,
                image_name=image_name,
                identity_image_name=identity_image_name,
                prompt=prompt,
                width=width,
                height=height,
            )

        source = request.get("inputImage") if isinstance(request, dict) else None
        if not isinstance(source, dict) or str(request.get("editTask") or "").strip().lower() != "character-sheet":
            return super()._generate_krea_identity_edit(
                request,
                model,
                image_name=image_name,
                prompt=prompt,
                width=width,
                height=height,
            )

        analysis = self._analyze_character_source(source)
        face_payload = self._prepare_v2_original_identity(source, analysis)
        if face_payload is None:
            result = super()._generate_krea_identity_edit(
                request,
                model,
                image_name=image_name,
                prompt=prompt,
                width=width,
                height=height,
            )
            if isinstance(result, dict):
                result["CharacterSheetBaseIdentityReference"] = False
            return result

        staged_face = self._stage_character_sheet_v2_source(face_payload)
        try:
            result = super()._generate_krea_identity_edit(
                request,
                model,
                image_name=image_name,
                identity_image_name=staged_face.name,
                prompt=prompt,
                width=width,
                height=height,
            )
        finally:
            staged_face.unlink(missing_ok=True)
        if isinstance(result, dict):
            result["CharacterSheetBaseIdentityReference"] = True
        return result

    def _persist_character_sheet_v2(
        self,
        request: dict[str, Any],
        base_result: dict[str, Any],
        final_path: Any,
        detail_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = super()._persist_character_sheet_v2(request, base_result, final_path, detail_results)
        if isinstance(result, dict):
            result["CharacterSheetBaseIdentityReference"] = bool(
                base_result.get("CharacterSheetBaseIdentityReference", False)
            )
        return result
