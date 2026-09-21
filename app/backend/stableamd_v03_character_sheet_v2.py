from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
_CHARACTER_SHEET_V2_DETAIL_PROMPT = (
    "Correct only the identity and fine facial/head details of image A so they match the same person in image B. "
    "Preserve image A's exact camera angle, head orientation, body pose, clothing, background, lighting and composition. "
    "Do not add another face, portrait inset, accessories, props or background objects. Remove malformed facial texture, "
    "duplicate features, ghost details and noisy artifacts inside the edited head region."
)
_LEGACY_CHARACTER_SHEET_FIELDS = {
    "characterSheetView",
    "characterSheetFraming",
    "characterSheetPhase",
    "characterSheetAnchorImagePath",
    "characterSheetBaseImagePath",
    "characterSheetBaseHistoryPath",
}


@dataclass(frozen=True)
class CharacterSheetV2Panel:
    role: str
    index: int
    path: Path
    box: tuple[int, int, int, int]
    detail_box: tuple[int, int, int, int]


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
    _CHARACTER_SHEET_V2_ROLES = ("face", "front", "three-quarter", "side", "back")
    _CHARACTER_SHEET_V2_PANEL_EDGE_INSET = 0.015
    _CHARACTER_SHEET_V2_LAYOUT = "five-panel-horizontal"

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

    @classmethod
    def _panel_regions(cls, width: int, height: int) -> list[CharacterSheetV2Panel]:
        width = int(width)
        height = int(height)
        if width < len(cls._CHARACTER_SHEET_V2_ROLES) or height <= 2:
            raise base.StableAmdBridgeError("Character Sheet v2 base image is too small to split into five panels.")
        boundaries = [round(index * width / len(cls._CHARACTER_SHEET_V2_ROLES)) for index in range(6)]
        regions: list[CharacterSheetV2Panel] = []
        for index, role in enumerate(cls._CHARACTER_SHEET_V2_ROLES):
            x0 = int(boundaries[index])
            x1 = int(boundaries[index + 1])
            panel_width = x1 - x0
            inset_x = max(1, int(round(panel_width * cls._CHARACTER_SHEET_V2_PANEL_EDGE_INSET)))
            inset_y = max(1, int(round(height * cls._CHARACTER_SHEET_V2_PANEL_EDGE_INSET)))
            inset_x = min(inset_x, max(1, panel_width // 3))
            inset_y = min(inset_y, max(1, height // 3))
            regions.append(
                CharacterSheetV2Panel(
                    role=role,
                    index=index,
                    path=Path(),
                    box=(x0, 0, x1, height),
                    detail_box=(inset_x, inset_y, panel_width - inset_x, height - inset_y),
                )
            )
        return regions

    @staticmethod
    def _should_detail_panel(role: str) -> bool:
        return str(role or "").strip().lower() in {"face", "front", "three-quarter", "side"}

    @staticmethod
    def _face_detail_box(
        face_box: Any,
        panel_size: tuple[int, int],
    ) -> tuple[int, int, int, int] | None:
        if not isinstance(face_box, (list, tuple)) or len(face_box) != 4:
            return None
        try:
            x0, y0, x1, y1 = (float(value) for value in face_box)
            panel_width, panel_height = (int(value) for value in panel_size)
        except (TypeError, ValueError):
            return None
        if panel_width <= 0 or panel_height <= 0 or x1 <= x0 or y1 <= y0:
            return None

        face_width = x1 - x0
        face_height = y1 - y0
        center_x = (x0 + x1) / 2.0
        center_y = (y0 + y1) / 2.0
        desired_width = max(16, int(round((face_width * 1.90) / 16.0)) * 16)
        desired_height = max(16, int(round((face_height * 2.30) / 16.0)) * 16)
        desired_width = min(panel_width - (panel_width % 16), desired_width)
        desired_height = min(panel_height - (panel_height % 16), desired_height)
        if desired_width < 16 or desired_height < 16:
            return None

        left = int(round(center_x - desired_width / 2.0))
        top = int(round(center_y - desired_height / 2.0))
        left = max(0, min(left, panel_width - desired_width))
        top = max(0, min(top, panel_height - desired_height))
        right = left + desired_width
        bottom = top + desired_height
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    def _stage_character_sheet_v2_source(self, source: Any) -> Path:
        parent_stage = getattr(super(), "_stage_character_sheet_v2_source", None)
        if callable(parent_stage):
            return parent_stage(source)
        return base.stage_input_image(self.repo_root, source)

    def _extract_v2_panels(self, base_path: Path) -> list[CharacterSheetV2Panel]:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet v2 panel extraction requires Pillow.") from exc

        path = Path(base_path).resolve()
        try:
            image = Image.open(path).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet v2 base image could not be decoded: {exc}") from exc
        output_root = self.repo_root / ".runtime" / "stableamd" / "output" / "character-sheet-v2"
        output_root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:12]
        panels: list[CharacterSheetV2Panel] = []
        for region in self._panel_regions(image.width, image.height):
            crop = image.crop(region.box)
            panel_path = output_root / f"{path.stem}-{token}-{region.index + 1}-{region.role}.png"
            crop.save(panel_path, format="PNG", optimize=True)
            panels.append(
                CharacterSheetV2Panel(
                    role=region.role,
                    index=region.index,
                    path=panel_path.resolve(),
                    box=region.box,
                    detail_box=region.detail_box,
                )
            )
        return panels

    @staticmethod
    def _feather_stitch(original: Any, refined: Any, crop_box: tuple[int, int, int, int], feather: float = 0.12) -> Any:
        try:
            from PIL import Image, ImageFilter
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet v2 stitching requires Pillow.") from exc

        x0, y0, x1, y1 = (int(value) for value in crop_box)
        if x1 <= x0 or y1 <= y0:
            raise base.StableAmdBridgeError("Character Sheet v2 detail crop is empty.")
        output = original.convert("RGB").copy()
        crop_width = x1 - x0
        crop_height = y1 - y0
        detailed = refined.convert("RGB").resize((crop_width, crop_height), Image.Resampling.LANCZOS)
        baseline = output.crop((x0, y0, x1, y1))
        mask = Image.new("L", (crop_width, crop_height), 255)
        feather = max(0.0, min(float(feather), 0.45))
        if feather > 0:
            edge = max(1, int(round(min(crop_width, crop_height) * feather)))
            inner = Image.new("L", (max(1, crop_width - 2 * edge), max(1, crop_height - 2 * edge)), 255)
            mask = Image.new("L", (crop_width, crop_height), 0)
            mask.paste(inner, (edge, edge))
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, edge / 2.0)))
        blended = Image.composite(detailed, baseline, mask)
        output.paste(blended, (x0, y0))
        return output

    def _reassemble_v2_panels(self, base_path: Path, panels: list[CharacterSheetV2Panel]) -> Path:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet v2 composition requires Pillow.") from exc

        base_path = Path(base_path).resolve()
        with Image.open(base_path) as source_image:
            canvas = source_image.convert("RGB").copy()
        for panel in sorted(panels, key=lambda item: item.index):
            with Image.open(panel.path) as panel_image:
                rendered = panel_image.convert("RGB")
            expected_size = (panel.box[2] - panel.box[0], panel.box[3] - panel.box[1])
            if rendered.size != expected_size:
                raise base.StableAmdBridgeError(
                    f"Character Sheet v2 panel '{panel.role}' changed size during detail refinement."
                )
            canvas.paste(rendered, (panel.box[0], panel.box[1]))
        output_root = self.repo_root / ".runtime" / "stableamd" / "output"
        output_root.mkdir(parents=True, exist_ok=True)
        destination = output_root / f"{base_path.stem}-character-sheet-v2.png"
        canvas.save(destination, format="PNG", optimize=True)
        return destination.resolve()

    @staticmethod
    def _character_sheet_v2_detail_prompt(role: str) -> str:
        if str(role or "").strip().lower() == "side":
            return _CHARACTER_SHEET_V2_DETAIL_PROMPT + " Preserve the current strict side profile exactly; do not rotate the face toward camera."
        return _CHARACTER_SHEET_V2_DETAIL_PROMPT

    def _prepare_v2_detail_context(
        self,
        panel: CharacterSheetV2Panel,
        source: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet v2 detail preprocessing requires Pillow.") from exc

        try:
            panel_image = Image.open(panel.path).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet v2 panel could not be decoded: {exc}") from exc
        dx0, dy0, dx1, dy1 = panel.detail_box
        analysis_image = panel_image.crop((dx0, dy0, dx1, dy1))
        analysis_payload = self._image_to_payload(analysis_image, f"{panel.role}-detail-analysis.png")
        analysis = self._analyze_character_source(analysis_payload)
        face_box = analysis.get("faceBox") if isinstance(analysis, dict) else None
        if not isinstance(face_box, (list, tuple)) or len(face_box) != 4:
            return None
        translated = [
            float(face_box[0]) + dx0,
            float(face_box[1]) + dy0,
            float(face_box[2]) + dx0,
            float(face_box[3]) + dy0,
        ]
        crop_box = self._face_detail_box(translated, panel_image.size)
        if crop_box is None:
            return None

        source_analysis = self._analyze_character_source(source)
        identity_payload = self._prepare_character_sheet_identity_reference(source, source_analysis)
        if identity_payload is None:
            return None

        scene_crop = panel_image.crop(crop_box)
        scene_payload = self._image_to_payload(scene_crop, f"{panel.role}-generated-head.png")
        scene = self._stage_character_sheet_v2_source(scene_payload)
        identity_staged: Path | None = None
        try:
            identity_staged = self._stage_character_sheet_v2_source(identity_payload)
        except Exception:
            scene.unlink(missing_ok=True)
            raise
        return {
            "scene": scene,
            "identity": identity_staged,
            "cropBox": crop_box,
            "width": crop_box[2] - crop_box[0],
            "height": crop_box[3] - crop_box[1],
        }

    def _stitch_v2_detail_result(
        self,
        panel: CharacterSheetV2Panel,
        refined_path: Any,
        crop_box: tuple[int, int, int, int],
    ) -> Path:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet v2 detail stitching requires Pillow.") from exc
        refined = Path(str(refined_path)).resolve()
        try:
            with Image.open(panel.path) as original_image:
                original = original_image.convert("RGB")
            with Image.open(refined) as refined_image:
                detailed = refined_image.convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet v2 detail result could not be decoded: {exc}") from exc
        stitched = self._feather_stitch(original, detailed, crop_box, feather=0.12)
        destination = panel.path.with_name(panel.path.stem + "-detailed.png")
        stitched.save(destination, format="PNG", optimize=True)
        return destination.resolve()

    def _refine_v2_panel(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        panel: CharacterSheetV2Panel,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._should_detail_panel(panel.role):
            return {
                "role": panel.role,
                "path": panel.path,
                "detailerStatus": "skipped",
                "detailerSkipped": "back-view",
            }

        context = self._prepare_v2_detail_context(panel, source)
        if context is None:
            return {
                "role": panel.role,
                "path": panel.path,
                "detailerStatus": "skipped",
                "detailerSkipped": "no-face",
            }

        scene = context["scene"]
        identity_reference = context["identity"]
        attempted = False
        try:
            attempted = True
            refined = self._generate_krea_identity_edit(
                request,
                model,
                image_name=scene.name,
                identity_image_name=identity_reference.name,
                prompt=self._character_sheet_v2_detail_prompt(panel.role),
                width=context["width"],
                height=context["height"],
            )
            refined_path = refined.get("ImagePath") if isinstance(refined, dict) else None
            if not refined_path:
                raise base.StableAmdBridgeError("Krea Identity Edit detailer did not return an image path.")
            stitched_path = self._stitch_v2_detail_result(panel, refined_path, context["cropBox"])
            return {
                "role": panel.role,
                "path": stitched_path,
                "detailerStatus": "completed",
                "detailerSkipped": None,
                "detailerPromptId": refined.get("PromptId"),
                "detailerHistoryPath": refined.get("HistoryPath"),
                "detailerGenerationSeconds": refined.get("GenerationSeconds") or 0.0,
                "detailCropBox": list(context["cropBox"]),
            }
        except base.StableAmdBridgeError as exc:
            return {
                "role": panel.role,
                "path": panel.path,
                "detailerStatus": "skipped",
                "detailerSkipped": "generation-failed",
                "detailerError": str(exc),
            }
        finally:
            if attempted:
                release = getattr(self, "_release_character_sheet_runtime", None)
                if callable(release):
                    release()
            scene.unlink(missing_ok=True)
            identity_reference.unlink(missing_ok=True)

    def _persist_character_sheet_v2(
        self,
        request: dict[str, Any],
        base_result: dict[str, Any],
        final_path: Path,
        detail_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        final_path = Path(final_path).resolve()
        output_root = (self.repo_root / ".runtime" / "stableamd" / "output").resolve()
        if output_root not in final_path.parents or not final_path.is_file():
            raise base.StableAmdBridgeError("Character Sheet v2 final image is outside the StableAMD output folder or missing.")

        prompt_id = uuid.uuid4().hex
        generation_seconds = 0.0
        try:
            generation_seconds += float(base_result.get("GenerationSeconds") or 0.0)
        except (TypeError, ValueError):
            pass
        items: list[dict[str, Any]] = []
        for item in detail_results:
            try:
                generation_seconds += float(item.get("detailerGenerationSeconds") or 0.0)
            except (TypeError, ValueError):
                pass
            items.append({
                "role": str(item.get("role") or ""),
                "imagePath": str(item.get("path") or ""),
                "detailerStatus": str(item.get("detailerStatus") or "skipped"),
                "detailerSkipped": item.get("detailerSkipped"),
                "detailerPromptId": item.get("detailerPromptId"),
                "detailCropBox": item.get("detailCropBox"),
            })

        prompt = str(base_result.get("Prompt") or self._character_sheet_v2_prompt(request.get("characterDescription")))
        record = {
            "schemaVersion": 3,
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "promptId": prompt_id,
            "mode": "character-sheet",
            "editOperation": "character-sheet-v2",
            "prompt": prompt,
            "negativePrompt": "",
            "modelId": str(base_result.get("ModelId") or request.get("modelId") or ""),
            "modelName": str(base_result.get("ModelName") or "Krea 2 Turbo"),
            "width": identity.KREA_IDENTITY_BASE_WIDTH,
            "height": identity.KREA_IDENTITY_BASE_HEIGHT,
            "seed": base_result.get("Seed"),
            "generationSeconds": round(generation_seconds, 3),
            "imagePath": str(final_path),
            "characterSheetVersion": self._CHARACTER_SHEET_V2_VERSION,
            "characterSheetLayout": self._CHARACTER_SHEET_V2_LAYOUT,
            "characterSheetViews": list(self._CHARACTER_SHEET_V2_ROLES),
            "characterSheetIdentityMode": "identity-edit-v1.2",
            "characterSheetIdentityLora": identity.KREA_IDENTITY_LORA_FILENAME,
            "characterSheetIdentityLoraStrength": identity.KREA_IDENTITY_LORA_STRENGTH,
            "characterSheetRefBoost": identity.KREA_IDENTITY_REF_BOOST,
            "characterSheetGroundingPx": identity.KREA_IDENTITY_GROUNDING_PX,
            "characterSheetBaseImagePath": str(base_result.get("ImagePath") or ""),
            "characterSheetDetailer": True,
            "characterSheetItems": items,
            "galleryHidden": False,
        }
        saver = getattr(self, "_save_bundle_history", None)
        if not callable(saver):
            raise base.StableAmdBridgeError("Character Sheet v2 cannot persist Gallery history.")
        history_path = saver(record)
        composite = {
            "ImagePath": str(final_path),
            "Width": identity.KREA_IDENTITY_BASE_WIDTH,
            "Height": identity.KREA_IDENTITY_BASE_HEIGHT,
            "Layout": self._CHARACTER_SHEET_V2_LAYOUT,
        }
        return {
            "PromptId": prompt_id,
            "Mode": "character-sheet",
            "EditOperation": "character-sheet-v2",
            "Prompt": prompt,
            "NegativePrompt": "",
            "ModelId": record["modelId"],
            "ModelName": record["modelName"],
            "Width": record["width"],
            "Height": record["height"],
            "Seed": record["seed"],
            "GenerationSeconds": record["generationSeconds"],
            "ImagePath": str(final_path),
            "HistoryPath": str(history_path),
            "CharacterSheetVersion": self._CHARACTER_SHEET_V2_VERSION,
            "CharacterSheetLayout": self._CHARACTER_SHEET_V2_LAYOUT,
            "CharacterSheetViews": list(self._CHARACTER_SHEET_V2_ROLES),
            "CharacterSheetIdentityMode": "identity-edit-v1.2",
            "CharacterSheetIdentityLora": identity.KREA_IDENTITY_LORA_FILENAME,
            "CharacterSheetIdentityLoraStrength": identity.KREA_IDENTITY_LORA_STRENGTH,
            "CharacterSheetRefBoost": identity.KREA_IDENTITY_REF_BOOST,
            "CharacterSheetGroundingPx": identity.KREA_IDENTITY_GROUNDING_PX,
            "CharacterSheetBaseImagePath": record["characterSheetBaseImagePath"],
            "CharacterSheetDetailer": True,
            "CharacterSheetItems": items,
            "CharacterSheetComposite": composite,
        }

    def _hide_character_sheet_v2_intermediates(
        self,
        base_result: dict[str, Any],
        detail_results: list[dict[str, Any]],
        final_result: dict[str, Any],
    ) -> None:
        hider = getattr(self, "_hide_character_sheet_child_history", None)
        if not callable(hider):
            return
        children: list[dict[str, Any]] = []
        base_history = str(base_result.get("HistoryPath") or "").strip()
        if base_history:
            children.append({"HistoryPath": base_history})
        for item in detail_results:
            history_path = str(item.get("detailerHistoryPath") or "").strip()
            if history_path:
                children.append({"HistoryPath": history_path})
        hider(
            children,
            str(final_result.get("PromptId") or ""),
            str(final_result.get("ImagePath") or ""),
        )

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

        if not bool(request.get("characterSheetDetailer", True)):
            return result

        panels = self._extract_v2_panels(Path(base_image))
        detail_results: list[dict[str, Any]] = []
        rendered_panels: list[CharacterSheetV2Panel] = []
        for panel in panels:
            detail_result = self._refine_v2_panel(request, selected, panel, source)
            detail_results.append(detail_result)
            rendered_panels.append(
                CharacterSheetV2Panel(
                    role=panel.role,
                    index=panel.index,
                    path=Path(str(detail_result.get("path") or panel.path)),
                    box=panel.box,
                    detail_box=panel.detail_box,
                )
            )

        final_path = self._reassemble_v2_panels(Path(base_image), rendered_panels)
        final_result = self._persist_character_sheet_v2(request, result, final_path, detail_results)
        self._hide_character_sheet_v2_intermediates(result, detail_results, final_result)
        return final_result

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
