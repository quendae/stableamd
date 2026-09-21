from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import local
from typing import Any

import stableamd_v03_krea_identity_edit as identity

base = identity.base

_CHARACTER_SHEET_V2_PROMPT = (
    "Create one clean character sheet of the exact same person or character from the reference image on a plain "
    "neutral grey studio background. Use five clearly separated panels from left to right: (1) close-up face portrait "
    "looking toward camera, (2) full-body front view, (3) full-body three-quarter view, (4) full-body strict side "
    "profile, (5) full-body back view. Preserve exact facial identity, age impression, hair, clothing, accessories, "
    "proportions, colors and materials. Do not add props, duplicate people, inset portraits, text, borders, scenery "
    "remnants, ghost anatomy or texture debris."
)
_LEGACY_CHARACTER_SHEET_FIELDS = {
    "characterSheetView",
    "characterSheetFraming",
    "characterSheetPhase",
    "characterSheetAnchorImagePath",
    "characterSheetBaseImagePath",
    "characterSheetBaseHistoryPath",
}


class KreaIdentityGenerationBridgeMixin:
    """Execute the normal Krea bundle runner while Identity Edit graph injection is active."""

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
        if not self._krea_identity_edit_ready():
            raise base.StableAmdBridgeError(
                "Krea Identity Edit is not ready. Install the pinned Identity Edit dependency and restart StableAMD."
            )
        width, height = self._validate_identity_target(width, height)
        clean = dict(request)
        for field in (
            "inputImage",
            "editTask",
            "references",
            "control",
            "characterSheetVersion",
            "characterDescription",
            "characterSheetDetailer",
            *sorted(_LEGACY_CHARACTER_SHEET_FIELDS),
            "denoise",
            "loraStack",
            "loraName",
            "loraModelStrength",
            "loraClipStrength",
        ):
            clean.pop(field, None)
        clean.update({
            "mode": "txt2img",
            "prompt": str(prompt),
            "width": width,
            "height": height,
            "steps": identity.KREA_IDENTITY_BASE_STEPS,
            "cfg": 1.0,
            "samplerName": "euler",
            "scheduler": "simple",
        })

        storage = getattr(self, "_stableamd_krea_identity_context", None)
        if storage is None:
            storage = local()
            self._stableamd_krea_identity_context = storage
        storage.value = {
            "image_name": str(image_name),
            "identity_image_name": str(identity_image_name or ""),
            "prompt": str(prompt),
            "width": width,
            "height": height,
        }
        try:
            return super()._generate_krea2_turbo(clean, model)
        finally:
            storage.value = None


class CharacterSheetV2BridgeMixin:
    _CHARACTER_SHEET_V2_VERSION = "v2-identity-edit"

    @staticmethod
    def _character_sheet_v2_prompt(description: Any = "") -> str:
        prompt = _CHARACTER_SHEET_V2_PROMPT
        text = str(description or "").strip()
        return f"{prompt} Character description: {text}" if text else prompt

    @staticmethod
    def _legacy_character_sheet_wire(request: dict[str, Any]) -> bool:
        version = str(request.get("characterSheetVersion") or "").strip().lower()
        if version == "legacy-sequential":
            return True
        if version:
            return False
        return any(field in request for field in _LEGACY_CHARACTER_SHEET_FIELDS)

    def _stage_character_sheet_v2_source(self, source: Any) -> Path:
        return base.stage_input_image(self.repo_root, source)

    def _persist_character_sheet_v2_base_metadata(
        self,
        result: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        raw_history = str(result.get("HistoryPath") or "").strip()
        if not raw_history or not hasattr(self, "repo_root"):
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        history_path = Path(raw_history).resolve()
        if history_root not in history_path.parents or not history_path.is_file():
            return
        try:
            record = json.loads(history_path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record.update({
                "mode": "character-sheet",
                "editOperation": "character-sheet-v2-base",
                "characterSheetVersion": metadata["CharacterSheetVersion"],
                "characterSheetIdentityLora": metadata["CharacterSheetIdentityLora"],
                "characterSheetIdentityLoraStrength": metadata["CharacterSheetIdentityLoraStrength"],
                "characterSheetRefBoost": metadata["CharacterSheetRefBoost"],
                "characterSheetGroundingPx": metadata["CharacterSheetGroundingPx"],
                "characterSheetBaseImagePath": metadata["CharacterSheetBaseImagePath"],
                "galleryHidden": False,
            })
            temporary = history_path.with_suffix(history_path.suffix + f".tmp-{uuid.uuid4().hex}")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(history_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise base.StableAmdBridgeError(
                f"Character Sheet v2 base generation completed, but its Gallery metadata could not be updated: {exc}"
            ) from exc

    def generate_character_sheet_v2(self, request: dict[str, Any]) -> dict[str, Any]:
        selected = self._selected_product_model(request)
        family = str((selected or {}).get("family") or (selected or {}).get("Family") or "").lower()
        asset_mode = str((selected or {}).get("assetMode") or (selected or {}).get("AssetMode") or "").lower()
        if not isinstance(selected, dict) or family != "krea2" or asset_mode != "bundle":
            raise base.StableAmdBridgeError("Character Sheet v2 requires the Krea 2 Turbo bundle.")
        if str(request.get("mode") or "").lower() != "img2img":
            raise base.StableAmdBridgeError("Character Sheet v2 requires Image to image mode.")
        if not self._krea_identity_edit_ready():
            raise base.StableAmdBridgeError(
                "Character Sheet v2 requires Krea Identity Edit. Install the pinned Identity Edit dependency and restart StableAMD."
            )
        if request.get("references"):
            raise base.StableAmdBridgeError("Character Sheet v2 manages its own identity references and does not accept extra references.")
        control_reader = getattr(self, "_control_request", None)
        if callable(control_reader) and control_reader(request) is not None:
            raise base.StableAmdBridgeError("Character Sheet v2 cannot be combined with Control guidance.")
        if request.get("loraStack") or str(request.get("loraName") or "").strip():
            raise base.StableAmdBridgeError("Character Sheet v2 owns the Identity Edit LoRA; disable regular LoRAs for this task.")
        source = request.get("inputImage")
        if not isinstance(source, dict):
            raise base.StableAmdBridgeError("Character Sheet v2 requires a source image.")

        description = str(request.get("characterDescription") or "").strip()
        prompt = self._character_sheet_v2_prompt(description)
        staged = self._stage_character_sheet_v2_source(source)
        try:
            result = self._generate_krea_identity_edit(
                request,
                selected,
                image_name=staged.name,
                prompt=prompt,
                width=identity.KREA_IDENTITY_BASE_WIDTH,
                height=identity.KREA_IDENTITY_BASE_HEIGHT,
            )
        finally:
            staged.unlink(missing_ok=True)

        release = getattr(self, "_release_character_sheet_runtime", None)
        if callable(release):
            release()

        base_image = str(result.get("ImagePath") or "")
        metadata = {
            "CharacterSheetVersion": self._CHARACTER_SHEET_V2_VERSION,
            "CharacterSheetIdentityLora": identity.KREA_IDENTITY_LORA_FILENAME,
            "CharacterSheetIdentityLoraStrength": identity.KREA_IDENTITY_LORA_STRENGTH,
            "CharacterSheetRefBoost": identity.KREA_IDENTITY_REF_BOOST,
            "CharacterSheetGroundingPx": identity.KREA_IDENTITY_GROUNDING_PX,
            "CharacterSheetBaseImagePath": base_image,
            "CharacterSheetDetailer": bool(request.get("characterSheetDetailer", True)),
        }
        result.update(metadata)
        result["Mode"] = "character-sheet"
        result["EditOperation"] = "character-sheet-v2-base"
        result["Prompt"] = prompt
        self._persist_character_sheet_v2_base_metadata(result, metadata)
        return result

    def generate(self, request: dict[str, Any]) -> Any:
        if str(request.get("editTask") or "").strip().lower() != "character-sheet":
            return super().generate(request)
        if self._legacy_character_sheet_wire(request):
            legacy = dict(request)
            legacy.pop("characterSheetVersion", None)
            legacy.pop("characterDescription", None)
            legacy.pop("characterSheetDetailer", None)
            return super().generate(legacy)

        version = str(request.get("characterSheetVersion") or "v2").strip().lower()
        if version != "v2":
            raise base.StableAmdBridgeError("characterSheetVersion must be v2 or legacy-sequential.")
        if not self._krea_identity_edit_ready():
            raise base.StableAmdBridgeError(
                "Character Sheet v2 requires Krea Identity Edit. Install the pinned Identity Edit dependency and restart StableAMD."
            )
        return self.generate_character_sheet_v2(request)


class CharacterSheetV2ApiMixin:
    _V2_FIELDS = {"characterSheetVersion", "characterDescription", "characterSheetDetailer"}

    @staticmethod
    def _has_legacy_sheet_fields(request: dict[str, Any]) -> bool:
        return any(field in request for field in _LEGACY_CHARACTER_SHEET_FIELDS)

    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        edit_task = request.get("editTask")
        version_value = request.get("characterSheetVersion")
        description = request.get("characterDescription", "")
        detailer = request.get("characterSheetDetailer", True)

        if edit_task != "character-sheet":
            if any(field in request for field in self._V2_FIELDS):
                raise ValueError("Character Sheet v2 fields are valid only when editTask is character-sheet.")
            return super()._validate_generation(request)

        if version_value is not None and (
            not isinstance(version_value, str)
            or version_value not in {"v2", "legacy-sequential"}
        ):
            raise ValueError("characterSheetVersion must be v2 or legacy-sequential.")

        version = str(version_value or "").strip()
        legacy_wire = version == "legacy-sequential" or (not version and self._has_legacy_sheet_fields(request))
        if legacy_wire:
            if "characterDescription" in request or "characterSheetDetailer" in request:
                raise ValueError("characterDescription and characterSheetDetailer are valid only for Character Sheet v2.")
            clean = dict(request)
            clean.pop("characterSheetVersion", None)
            validated = super()._validate_generation(clean)
            if version == "legacy-sequential":
                validated["characterSheetVersion"] = "legacy-sequential"
            return validated

        # Bare character-sheet requests now select v2. The old wire remains
        # backward-compatible only when one of its view/phase fields is present.
        for field in _LEGACY_CHARACTER_SHEET_FIELDS:
            if field in request:
                raise ValueError(f"{field} is a legacy-sequential field and is not valid for Character Sheet v2.")
        if not isinstance(description, str):
            raise ValueError("characterDescription must be a string.")
        if len(description) > 1000:
            raise ValueError("characterDescription must be 1000 characters or fewer.")
        if not isinstance(detailer, bool):
            raise ValueError("characterSheetDetailer must be boolean.")
        if request.get("references"):
            raise ValueError("Character Sheet v2 manages its own identity references and does not accept extra references.")

        clean = dict(request)
        clean.pop("editTask", None)
        clean.pop("characterSheetVersion", None)
        clean.pop("characterDescription", None)
        clean.pop("characterSheetDetailer", None)
        validated = super()._validate_generation(clean)
        if validated.get("mode", "txt2img") != "img2img":
            raise ValueError("Character Sheet v2 is valid only for img2img generation.")
        validated["editTask"] = "character-sheet"
        validated["characterSheetVersion"] = "v2"
        validated["characterDescription"] = description.strip()
        validated["characterSheetDetailer"] = detailer
        return validated
