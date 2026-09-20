from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import stableamd_v03_krea_edit as kreaedit

base = kreaedit.base


class CharacterSheetBridgeMixin:
    """Sequential single-view character sheet generation for Krea Image Edit."""

    _CHARACTER_SHEET_WIDTH = 1024
    _CHARACTER_SHEET_HEIGHT = 1024
    _CHARACTER_SHEET_VIEWS = (
        "face-close-up",
        "front",
        "three-quarter",
        "side",
        "back",
    )
    _CHARACTER_SHEET_DEFAULT_PROMPT = (
        "Preserve the exact same character from Picture 1: identity, facial features, hairstyle or fur, "
        "clothing, accessories, body proportions, colors, materials, and art style. Keep the design "
        "consistent across every generated view. Use a clean neutral studio background with soft even "
        "lighting. Do not add text, labels, props, alternate outfits, or extra characters."
    )
    _CHARACTER_SHEET_VIEW_PROMPTS = {
        "face-close-up": (
            "Create a single close-up portrait of the same character, centered and facing the camera. "
            "Frame the head and upper shoulders clearly so facial features and identity cues are easy to inspect. "
            "Use a neutral relaxed expression."
        ),
        "front": (
            "Create a single full-body front view of the same character, facing straight toward the camera. "
            "Show the complete character from head to toe at a neutral relaxed stance and natural proportions."
        ),
        "three-quarter": (
            "Create a single full-body three-quarter view of the same character, rotated about 45 degrees from the camera. "
            "Show the complete character from head to toe in a neutral relaxed stance."
        ),
        "side": (
            "Create a single full-body strict side profile of the same character. Show the complete character from head to toe, "
            "with the body and head oriented consistently in profile and a neutral relaxed stance."
        ),
        "back": (
            "Create a single full-body back view of the same character, facing directly away from the camera. "
            "Show the complete character from head to toe in a neutral relaxed stance and preserve rear costume, hair, tail, and accessory details."
        ),
    }

    @classmethod
    def _build_character_sheet_instruction(cls, view: str, notes: str = "") -> str:
        normalized_view = str(view or "").strip().lower()
        if normalized_view not in cls._CHARACTER_SHEET_VIEWS:
            raise base.StableAmdBridgeError(
                "Character sheet view must be face-close-up, front, three-quarter, side, or back."
            )
        user_prompt = str(notes or "").strip() or cls._CHARACTER_SHEET_DEFAULT_PROMPT
        view_prompt = cls._CHARACTER_SHEET_VIEW_PROMPTS[normalized_view]
        return (
            f"{user_prompt} Show only one character in the image. {view_prompt} "
            "Keep camera perspective, character scale, design language, colors, and lighting consistent with the other character-sheet views."
        )

    def model_support(self) -> dict[str, Any]:
        support = super().model_support()
        if not isinstance(support, dict):
            return support

        for entry in support.get("models", []):
            if not isinstance(entry, dict) or str(entry.get("family") or "").lower() != "krea2":
                continue
            policy = entry.get("editPolicy")
            if not isinstance(policy, dict):
                continue
            tasks = [
                item for item in policy.get("tasks", [])
                if isinstance(item, dict) and item.get("id") != "character-turnaround"
            ]
            tasks.append({
                "id": "character-sheet",
                "label": "Character sheet",
                "referenceImages": 0,
                "masked": False,
                "sourceSizeOutput": False,
                "outputSize": {
                    "width": self._CHARACTER_SHEET_WIDTH,
                    "height": self._CHARACTER_SHEET_HEIGHT,
                },
                "generationMode": "sequential",
                "views": list(self._CHARACTER_SHEET_VIEWS),
            })
            policy["tasks"] = tasks
        return support

    def _persist_character_sheet_view_metadata(
        self,
        result: dict[str, Any],
        view: str,
    ) -> None:
        result["EditOperation"] = "character-sheet-view"
        result["CharacterSheetView"] = view
        result["CharacterSheetWidth"] = self._CHARACTER_SHEET_WIDTH
        result["CharacterSheetHeight"] = self._CHARACTER_SHEET_HEIGHT

        raw_history = str(result.get("HistoryPath") or "").strip()
        if not raw_history:
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        history_path = Path(raw_history).resolve()
        if history_root not in history_path.parents or not history_path.is_file():
            return
        try:
            record = json.loads(history_path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record["editOperation"] = "character-sheet-view"
            record["characterSheetView"] = view
            record["characterSheetWidth"] = self._CHARACTER_SHEET_WIDTH
            record["characterSheetHeight"] = self._CHARACTER_SHEET_HEIGHT
            temporary = history_path.with_suffix(history_path.suffix + ".tmp-character-sheet")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(history_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise base.StableAmdBridgeError(
                f"Character sheet view completed, but Gallery metadata could not be updated: {exc}"
            ) from exc

    def generate(self, request: dict[str, Any]) -> Any:
        edit_task = str(request.get("editTask") or "").strip().lower()
        if edit_task != "character-sheet":
            return super().generate(request)

        selected = self._selected_product_model(request)
        family = ""
        asset_mode = ""
        if isinstance(selected, dict):
            family = str(selected.get("family") or selected.get("Family") or "").lower()
            asset_mode = str(selected.get("assetMode") or selected.get("AssetMode") or "").lower()
        mode = str(request.get("mode") or "txt2img").lower()
        if family != "krea2" or asset_mode != "bundle" or mode != "img2img":
            raise base.StableAmdBridgeError("Character sheet currently requires Krea 2 Image Edit.")
        if not self._krea_image_edit_ready():
            raise base.StableAmdBridgeError(
                "Krea 2 Image Edit is not ready. Install/restart the pinned Krea edit integration first."
            )
        if request.get("references"):
            raise base.StableAmdBridgeError(
                "Character sheet uses only the source character image and does not accept extra references."
            )
        control_reader = getattr(self, "_control_request", None)
        if callable(control_reader) and control_reader(request) is not None:
            raise base.StableAmdBridgeError(
                "Character sheet and Control guidance cannot be combined in the first Character Sheet gate."
            )

        view = str(request.get("characterSheetView") or "").strip().lower()
        if view not in self._CHARACTER_SHEET_VIEWS:
            raise base.StableAmdBridgeError(
                "Character sheet view must be face-close-up, front, three-quarter, side, or back."
            )

        source = request.get("inputImage")
        source_name = str(source.get("name") or "source-image") if isinstance(source, dict) else "source-image"
        staged = base.stage_input_image(self.repo_root, source)

        clean = dict(request)
        clean["mode"] = "txt2img"
        clean["prompt"] = self._build_character_sheet_instruction(view, str(request.get("prompt") or ""))
        clean["width"] = self._CHARACTER_SHEET_WIDTH
        clean["height"] = self._CHARACTER_SHEET_HEIGHT
        clean.pop("inputImage", None)
        clean.pop("denoise", None)
        clean.pop("control", None)
        clean.pop("references", None)
        clean.pop("editTask", None)
        clean.pop("characterSheetView", None)

        self._stableamd_krea_edit_context.value = {
            "image_name": staged.name,
            "source_name": source_name,
            "references": [],
            "output_size": {
                "width": self._CHARACTER_SHEET_WIDTH,
                "height": self._CHARACTER_SHEET_HEIGHT,
            },
        }
        try:
            result = self._generate_krea2_turbo(clean, selected)
        finally:
            self._stableamd_krea_edit_context.value = None
            staged.unlink(missing_ok=True)

        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Krea 2 Character Sheet provider did not return a result object.")
        self._persist_krea_image_edit_metadata(
            result,
            source_name,
            edit_operation="character-sheet-view",
        )
        self._persist_character_sheet_view_metadata(result, view)
        return result
