from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import stableamd_v03_character_sheet as sheet

base = sheet.base


class CharacterSheetAnchorBridgeMixin:
    """Second-pass identity refinement for visible-face Character Sheet views.

    The first FACE render becomes a generated identity anchor for the rest of
    the sheet. FRONT / 3/4 / SIDE are first composed normally, then edited a
    second time with the generated view as Picture 1, the original tight face
    crop as Picture 2 when available, and the FACE result as the final content
    reference. The refinement is intentionally narrow: preserve pose, body,
    clothing, framing and background while correcting head/face identity.
    """

    _CHARACTER_SHEET_REFINE_VIEWS = {"front", "three-quarter", "side"}

    def _managed_character_sheet_output_payload(self, raw_path: Any) -> dict[str, str]:
        path = self._validated_character_sheet_output_path(raw_path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise base.StableAmdBridgeError(f"Character Sheet managed image could not be read: {exc}") from exc
        suffix = path.suffix.lower()
        mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/webp" if suffix == ".webp" else "image/png"
        return {
            "name": path.name,
            "mimeType": mime,
            "dataBase64": base64.b64encode(data).decode("ascii"),
        }

    @staticmethod
    def _build_character_sheet_refine_instruction(
        view: str,
        notes: str,
        has_original_face: bool,
    ) -> str:
        view = str(view or "").strip().lower()
        user_prompt = str(notes or "").strip()
        if has_original_face:
            references = (
                "Picture 2 is a tight crop from the original source and is authoritative for the original facial identity, "
                "age impression, face shape, eyes, nose, mouth, skin tone, hairline, hairstyle and head accessories. "
                "Picture 3 is the generated FACE anchor from this same character sheet and supplies consistent generated-view identity."
            )
        else:
            references = (
                "Picture 2 is the generated FACE anchor from this same character sheet and is the identity reference for the head and face."
            )
        view_rule = {
            "front": "Keep the face front-facing exactly as Picture 1 is posed.",
            "three-quarter": "Keep the existing three-quarter head angle and adapt the same identity to that angle.",
            "side": "Keep the strict side-profile pose; adapt the same identity to profile without turning the face toward camera.",
        }.get(view, "Keep the existing head angle from Picture 1.")
        prefix = f"{user_prompt} " if user_prompt else ""
        return (
            f"{prefix}Identity refinement pass. Picture 1 is the already generated character-sheet view. "
            f"Preserve Picture 1 composition, pose, body proportions, clothing, accessories, hands, legs, camera, lighting and background exactly. "
            f"{references} Change only the head/face/hair details needed to make Picture 1 match the identity references. "
            f"{view_rule} Do not add another person, portrait inset, duplicate head, extra face, props or scene elements. "
            "Do not redesign or beautify the person. Keep natural photographic texture and preserve the original age impression."
        )

    def _hide_character_sheet_intermediate_history(self, raw_path: Any, refined_prompt_id: str) -> None:
        raw = str(raw_path or "").strip()
        if not raw:
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        path = Path(raw).resolve()
        if history_root not in path.parents or not path.is_file():
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record["galleryHidden"] = True
            record["characterSheetIntermediate"] = True
            record["characterSheetRefinedByPromptId"] = refined_prompt_id
            temporary = path.with_suffix(path.suffix + ".tmp-refined")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return

    def _persist_character_sheet_refine_metadata(
        self,
        result: dict[str, Any],
        anchor_path: str,
        base_path: str,
    ) -> None:
        result["CharacterSheetPhase"] = "identity-refined"
        result["CharacterSheetIdentityMode"] = "anchor-refine"
        result["CharacterSheetAnchorImagePath"] = anchor_path
        result["CharacterSheetBaseImagePath"] = base_path
        raw_history = str(result.get("HistoryPath") or "").strip()
        if not raw_history:
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        path = Path(raw_history).resolve()
        if history_root not in path.parents or not path.is_file():
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record["characterSheetPhase"] = "identity-refined"
            record["characterSheetIdentityMode"] = "anchor-refine"
            record["characterSheetAnchorImagePath"] = anchor_path
            record["characterSheetBaseImagePath"] = base_path
            temporary = path.with_suffix(path.suffix + ".tmp-anchor")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return

    def _generate_character_sheet_identity_refine(self, request: dict[str, Any]) -> Any:
        selected = self._selected_product_model(request)
        family = ""
        asset_mode = ""
        if isinstance(selected, dict):
            family = str(selected.get("family") or selected.get("Family") or "").lower()
            asset_mode = str(selected.get("assetMode") or selected.get("AssetMode") or "").lower()
        if family != "krea2" or asset_mode != "bundle" or str(request.get("mode") or "").lower() != "img2img":
            raise base.StableAmdBridgeError("Character Sheet identity refinement requires Krea 2 Image Edit.")
        if not self._krea_image_edit_ready():
            raise base.StableAmdBridgeError("Krea 2 Image Edit is not ready for Character Sheet identity refinement.")

        view = str(request.get("characterSheetView") or "").strip().lower()
        if view not in self._CHARACTER_SHEET_REFINE_VIEWS:
            raise base.StableAmdBridgeError("Character Sheet identity refinement is available only for front, three-quarter, and side views.")
        requested_framing = str(request.get("characterSheetFraming") or "auto").strip().lower()
        source = request.get("inputImage")
        source_name = str(source.get("name") or "source-image") if isinstance(source, dict) else "source-image"

        _, resolved_framing, analysis, width, height = self._prepare_character_sheet_reference(
            source,
            view,
            requested_framing,
        )
        original_face_payload = self._prepare_character_sheet_identity_reference(source, analysis)
        base_path = self._validated_character_sheet_output_path(request.get("characterSheetBaseImagePath"))
        anchor_path = self._validated_character_sheet_output_path(request.get("characterSheetAnchorImagePath"))
        base_payload = self._managed_character_sheet_output_payload(base_path)
        anchor_payload = self._managed_character_sheet_output_payload(anchor_path)

        staged_source = base.stage_input_image(self.repo_root, base_payload)
        staged_references: list[Path] = []
        internal_references: list[dict[str, str]] = []
        if original_face_payload is not None:
            staged_original_face = base.stage_input_image(self.repo_root, original_face_payload)
            staged_references.append(staged_original_face)
            internal_references.append({"name": staged_original_face.name, "role": "content"})
        staged_anchor = base.stage_input_image(self.repo_root, anchor_payload)
        staged_references.append(staged_anchor)
        internal_references.append({"name": staged_anchor.name, "role": "content"})

        clean = dict(request)
        clean["mode"] = "txt2img"
        clean["prompt"] = self._build_character_sheet_refine_instruction(
            view,
            str(request.get("prompt") or ""),
            original_face_payload is not None,
        )
        clean["width"] = width
        clean["height"] = height
        for key in (
            "inputImage",
            "denoise",
            "control",
            "references",
            "editTask",
            "characterSheetView",
            "characterSheetFraming",
            "characterSheetPhase",
            "characterSheetAnchorImagePath",
            "characterSheetBaseImagePath",
            "characterSheetBaseHistoryPath",
        ):
            clean.pop(key, None)

        self._stableamd_krea_edit_context.value = {
            "image_name": staged_source.name,
            "source_name": source_name,
            "references": internal_references,
            "output_size": {"width": width, "height": height},
        }
        try:
            result = self._generate_krea2_turbo(clean, selected)
        finally:
            self._stableamd_krea_edit_context.value = None
            staged_source.unlink(missing_ok=True)
            for staged in staged_references:
                staged.unlink(missing_ok=True)
            self._release_character_sheet_runtime()

        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Krea 2 Character Sheet identity refinement did not return a result object.")
        self._persist_krea_image_edit_metadata(
            result,
            source_name,
            references=internal_references,
            edit_operation="character-sheet-view",
        )
        self._persist_character_sheet_view_metadata(
            result,
            view,
            requested_framing,
            resolved_framing,
            width,
            height,
            analysis,
            identity_reference=True,
        )
        self._persist_character_sheet_refine_metadata(result, str(anchor_path), str(base_path))
        self._hide_character_sheet_intermediate_history(
            request.get("characterSheetBaseHistoryPath"),
            str(result.get("PromptId") or ""),
        )
        return result

    def generate(self, request: dict[str, Any]) -> Any:
        if (
            str(request.get("editTask") or "").strip().lower() == "character-sheet"
            and str(request.get("characterSheetPhase") or "base").strip().lower() == "identity-refine"
        ):
            return self._generate_character_sheet_identity_refine(request)
        return super().generate(request)
