from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import stableamd_v03_krea_edit as kreaedit

base = kreaedit.base


class CharacterSheetBridgeMixin:
    """Identity-focused sequential Character Sheet generation for Krea Image Edit.

    A framing-aware body/source reference is reused across five independent
    generation jobs. When DWPose detects a human face, StableAMD also creates a
    private face crop and feeds it to Krea as Picture 2 so facial identity gets
    substantially more reference pixels without asking the user for another
    image. The five generated views are finally composed into one persisted PNG
    without another diffusion pass.
    """

    _CHARACTER_SHEET_VIEWS = (
        "face-close-up",
        "front",
        "three-quarter",
        "side",
        "back",
    )
    _CHARACTER_SHEET_FRAMING_MODES = ("auto", "portrait", "full-body")
    _CHARACTER_SHEET_COMPOSITE_LAYOUT = "grid-3x2"
    _CHARACTER_SHEET_FACE_SIZE = (1024, 1024)
    _CHARACTER_SHEET_PORTRAIT_SIZE = (896, 1152)
    _CHARACTER_SHEET_FULL_BODY_SIZE = (832, 1216)
    _CHARACTER_SHEET_IDENTITY_SIZE = (768, 768)
    _CHARACTER_SHEET_DEFAULT_PROMPT = (
        "Preserve the exact same person or character from Picture 1. Treat identity as fixed, not approximate: "
        "keep face shape, eyes, nose, mouth, age impression, hairstyle or fur, skin or fur tone, clothing, "
        "accessories, body proportions, colors, materials, and art style consistent across every view. "
        "Ignore background scenery, landmarks, furniture, statues, and other props from Picture 1. Use a clean "
        "neutral studio background with soft even lighting. Do not add text, labels, props, alternate outfits, "
        "extra characters, facial distortions, or identity drift."
    )
    _SCORE_THRESHOLD = 0.20

    @staticmethod
    def _view_label(view: str) -> str:
        return {
            "face-close-up": "FACE",
            "front": "FRONT",
            "three-quarter": "3/4",
            "side": "SIDE",
            "back": "BACK",
        }.get(str(view or "").lower(), str(view or "VIEW").upper())

    @classmethod
    def _character_sheet_output_size(
        cls,
        view: str,
        framing: str,
        source_size: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        view = str(view or "").strip().lower()
        framing = str(framing or "source").strip().lower()
        if view == "face-close-up":
            return cls._CHARACTER_SHEET_FACE_SIZE
        if framing == "portrait":
            return cls._CHARACTER_SHEET_PORTRAIT_SIZE
        if framing == "full-body":
            return cls._CHARACTER_SHEET_FULL_BODY_SIZE
        if source_size and source_size[0] > 0 and source_size[1] > 0:
            source_width, source_height = source_size
            ratio = source_width / source_height
            target_pixels = 1024 * 1024
            width = math.sqrt(target_pixels * ratio)
            height = width / ratio
            max_dimension = 1216.0
            scale = min(1.0, max_dimension / max(width, height))
            width *= scale
            height *= scale

            def align16(value: float) -> int:
                return max(512, int(round(value / 16.0)) * 16)

            return align16(width), align16(height)
        return 1024, 1024

    @classmethod
    def _build_character_sheet_instruction(
        cls,
        view: str,
        notes: str = "",
        framing: str = "portrait",
    ) -> str:
        normalized_view = str(view or "").strip().lower()
        normalized_framing = str(framing or "portrait").strip().lower()
        if normalized_view not in cls._CHARACTER_SHEET_VIEWS:
            raise base.StableAmdBridgeError(
                "Character sheet view must be face-close-up, front, three-quarter, side, or back."
            )
        user_prompt = str(notes or "").strip() or cls._CHARACTER_SHEET_DEFAULT_PROMPT

        identity_prompt = (
            "Picture 1 is the primary body, clothing, accessories, proportions, colors, and material reference. "
            "When Picture 2 is present, Picture 2 is the identity reference and is authoritative for facial identity, "
            "face shape, eyes, nose, mouth, skin tone, age impression, hairstyle or fur, and other head details. "
            "Do not average the identity with another person or object. Ignore background scenery, landmarks, furniture, "
            "statues, and other props from Picture 1; they are not part of the character."
        )

        if normalized_view == "face-close-up":
            view_prompt = (
                "Create a single close-up portrait of the same character, centered and facing the camera. "
                "Frame the head and upper shoulders clearly so facial features and identity cues are easy to inspect. "
                "Use a neutral relaxed expression."
            )
        else:
            view_name = {
                "front": "front view, facing straight toward the camera",
                "three-quarter": "three-quarter view, rotated about 45 degrees from the camera",
                "side": "strict side profile, with the head and body consistently in profile",
                "back": "back view, facing directly away from the camera",
            }[normalized_view]
            if normalized_framing == "full-body":
                view_prompt = (
                    f"Create a single full-body {view_name} of the same character. "
                    "Show the complete character from head to toe in a neutral relaxed stance with natural proportions."
                )
            elif normalized_framing == "source":
                view_prompt = (
                    f"Create a single {view_name} of the same character. Keep approximately the same visible-body coverage "
                    "and camera distance as Picture 1; do not force a full-body reconstruction when the source does not show it. "
                    "Use a neutral relaxed pose."
                )
            else:
                view_prompt = (
                    f"Create a single upper body {view_name} of the same character. Frame the head, shoulders, and torso clearly, "
                    "keeping a consistent portrait camera distance and a neutral relaxed pose."
                )

        return (
            f"{user_prompt} {identity_prompt} Show only one character in the image. {view_prompt} "
            "Keep camera perspective, character scale, design language, colors, and lighting consistent with the other character-sheet views. "
            "Keep the image clean and photographic or stylistically faithful to the source; avoid duplicate anatomy, smeared textures, "
            "ghost details, background-object remnants, and malformed accessories."
        )

    @classmethod
    def _analyze_dwpose_candidates(
        cls,
        candidates: Any,
        scores: Any,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        try:
            import numpy as np
        except Exception:
            return {"detected": False, "framing": "source", "sourceSize": [width, height]}

        points = np.asarray(candidates, dtype=float)
        confidences = np.asarray(scores, dtype=float)
        if points.ndim != 3 or confidences.ndim != 2 or points.shape[0] != confidences.shape[0]:
            return {"detected": False, "framing": "source", "sourceSize": [width, height]}

        selected: dict[str, Any] | None = None
        for person_index in range(points.shape[0]):
            person_points = points[person_index]
            person_scores = confidences[person_index]
            if person_points.shape[0] < 18 or person_scores.shape[0] < 18:
                continue
            body_visible = person_scores[:18] > cls._SCORE_THRESHOLD
            if int(np.count_nonzero(body_visible)) < 4:
                continue

            all_count = min(person_points.shape[0], person_scores.shape[0])
            visible = person_scores[:all_count] > cls._SCORE_THRESHOLD
            xy = person_points[:all_count, :2][visible]
            xy = xy[np.isfinite(xy).all(axis=1)]
            if xy.size == 0:
                continue
            x0 = float(max(0.0, np.min(xy[:, 0])))
            y0 = float(max(0.0, np.min(xy[:, 1])))
            x1 = float(min(float(width), np.max(xy[:, 0])))
            y1 = float(min(float(height), np.max(xy[:, 1])))
            if x1 <= x0 or y1 <= y0:
                continue

            body = person_scores[:18]
            has_hip = any(body[index] > cls._SCORE_THRESHOLD for index in (8, 11))
            has_knee = any(body[index] > cls._SCORE_THRESHOLD for index in (9, 12))
            has_ankle = any(body[index] > cls._SCORE_THRESHOLD for index in (10, 13))
            framing = "full-body" if (has_hip and has_knee and has_ankle) else "portrait"

            face_indices: list[int] = []
            if person_points.shape[0] >= 92 and person_scores.shape[0] >= 92:
                face_indices.extend(
                    index for index in range(24, 92)
                    if person_scores[index] > cls._SCORE_THRESHOLD
                )
            face_indices.extend(
                index for index in (0, 1, 2, 5, 14, 15, 16, 17)
                if index < person_scores.shape[0] and person_scores[index] > cls._SCORE_THRESHOLD
            )
            face_box = None
            if face_indices:
                unique = sorted(set(face_indices))
                face_xy = person_points[unique, :2]
                face_xy = face_xy[np.isfinite(face_xy).all(axis=1)]
                if face_xy.size:
                    fx0 = float(max(0.0, np.min(face_xy[:, 0])))
                    fy0 = float(max(0.0, np.min(face_xy[:, 1])))
                    fx1 = float(min(float(width), np.max(face_xy[:, 0])))
                    fy1 = float(min(float(height), np.max(face_xy[:, 1])))
                    if fx1 > fx0 and fy1 > fy0:
                        face_box = [fx0, fy0, fx1, fy1]

            candidate = {
                "detected": True,
                "framing": framing,
                "subjectBox": [x0, y0, x1, y1],
                "faceBox": face_box,
                "sourceSize": [int(width), int(height)],
                "area": (x1 - x0) * (y1 - y0),
            }
            if selected is None or candidate["area"] > selected["area"]:
                selected = candidate

        if selected is None:
            return {"detected": False, "framing": "source", "sourceSize": [width, height]}
        selected.pop("area", None)
        return selected

    def _analyze_character_source(self, source: Any) -> dict[str, Any]:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet preprocessing requires Pillow.") from exc

        _, image_bytes = base._decode_input_image(source)
        digest = hashlib.sha256(image_bytes).hexdigest()
        cache = getattr(self, "_stableamd_character_sheet_analysis_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._stableamd_character_sheet_analysis_cache = cache
        cached = cache.get(digest)
        if isinstance(cached, dict):
            return dict(cached)

        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet source image could not be decoded: {exc}") from exc
        width, height = image.size
        fallback = {"detected": False, "framing": "source", "sourceSize": [width, height]}

        ready = getattr(self, "_dwpose_ready", None)
        loader = getattr(self, "_load_dwpose_runtime", None)
        if not callable(ready) or not callable(loader):
            cache[digest] = fallback
            return dict(fallback)
        try:
            if not ready():
                cache[digest] = fallback
                return dict(fallback)
            import numpy as np
            runtime = loader()
            candidates, scores = runtime(np.asarray(image))
            analysis = self._analyze_dwpose_candidates(candidates, scores, width, height)
        except Exception:
            analysis = fallback
        cache[digest] = analysis
        return dict(analysis)

    @staticmethod
    def _crop_reference_to_subject(
        image: Any,
        bbox: tuple[float, float, float, float] | list[float],
        target_width: int,
        target_height: int,
        margin: float = 0.20,
    ) -> Any:
        source_width, source_height = image.size
        x0, y0, x1, y1 = (float(value) for value in bbox)
        x0 = max(0.0, min(float(source_width), x0))
        y0 = max(0.0, min(float(source_height), y0))
        x1 = max(x0 + 1.0, min(float(source_width), x1))
        y1 = max(y0 + 1.0, min(float(source_height), y1))

        box_width = x1 - x0
        box_height = y1 - y0
        x0 -= box_width * margin
        x1 += box_width * margin
        y0 -= box_height * margin
        y1 += box_height * margin
        box_width = x1 - x0
        box_height = y1 - y0
        ratio = float(target_width) / float(target_height)

        if box_width / box_height < ratio:
            desired_width = box_height * ratio
            delta = desired_width - box_width
            x0 -= delta / 2.0
            x1 += delta / 2.0
        else:
            desired_height = box_width / ratio
            delta = desired_height - box_height
            y0 -= delta / 2.0
            y1 += delta / 2.0

        crop_width = x1 - x0
        crop_height = y1 - y0
        scale = min(1.0, source_width / crop_width, source_height / crop_height)
        crop_width *= scale
        crop_height *= scale
        center_x = (x0 + x1) / 2.0
        center_y = (y0 + y1) / 2.0
        left = center_x - crop_width / 2.0
        top = center_y - crop_height / 2.0
        left = min(max(0.0, left), max(0.0, source_width - crop_width))
        top = min(max(0.0, top), max(0.0, source_height - crop_height))
        right = left + crop_width
        bottom = top + crop_height

        left_i = max(0, int(round(left)))
        top_i = max(0, int(round(top)))
        right_i = min(source_width, max(left_i + 1, int(round(right))))
        bottom_i = min(source_height, max(top_i + 1, int(round(bottom))))
        return image.crop((left_i, top_i, right_i, bottom_i))

    @staticmethod
    def _isolate_reference_subject(
        image: Any,
        bbox: tuple[float, float, float, float] | list[float],
        target_width: int,
        target_height: int,
        margin: float = 0.12,
    ) -> Any:
        """Crop around the detected subject, then pad instead of widening into scene props."""
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet preprocessing requires Pillow.") from exc

        source_width, source_height = image.size
        x0, y0, x1, y1 = (float(value) for value in bbox)
        x0 = max(0.0, min(float(source_width), x0))
        y0 = max(0.0, min(float(source_height), y0))
        x1 = max(x0 + 1.0, min(float(source_width), x1))
        y1 = max(y0 + 1.0, min(float(source_height), y1))
        box_width = x1 - x0
        box_height = y1 - y0
        x0 = max(0.0, x0 - box_width * margin)
        x1 = min(float(source_width), x1 + box_width * margin)
        y0 = max(0.0, y0 - box_height * margin)
        y1 = min(float(source_height), y1 + box_height * margin)

        left = max(0, int(math.floor(x0)))
        top = max(0, int(math.floor(y0)))
        right = min(source_width, max(left + 1, int(math.ceil(x1))))
        bottom = min(source_height, max(top + 1, int(math.ceil(y1))))
        cropped = image.crop((left, top, right, bottom)).convert("RGB")

        scale = min(float(target_width) / float(cropped.width), float(target_height) / float(cropped.height))
        resized_size = (
            max(1, int(round(cropped.width * scale))),
            max(1, int(round(cropped.height * scale))),
        )
        resized = cropped.resize(resized_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (target_width, target_height), (242, 242, 242))
        paste_x = (target_width - resized.width) // 2
        paste_y = (target_height - resized.height) // 2
        canvas.paste(resized, (paste_x, paste_y))
        return canvas

    @staticmethod
    def _image_to_payload(image: Any, name: str) -> dict[str, str]:
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return {
            "name": name,
            "mimeType": "image/png",
            "dataBase64": base64.b64encode(output.getvalue()).decode("ascii"),
        }

    def _prepare_character_sheet_identity_reference(
        self,
        source: Any,
        analysis: dict[str, Any],
    ) -> dict[str, str] | None:
        if not bool(analysis.get("detected")):
            return None
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet identity preprocessing requires Pillow.") from exc

        _, image_bytes = base._decode_input_image(source)
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet identity source could not be decoded: {exc}") from exc

        bbox = analysis.get("faceBox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            subject_box = analysis.get("subjectBox")
            if not (isinstance(subject_box, (list, tuple)) and len(subject_box) == 4):
                return None
            sx0, sy0, sx1, sy1 = (float(value) for value in subject_box)
            subject_width = max(1.0, sx1 - sx0)
            subject_height = max(1.0, sy1 - sy0)
            center_x = (sx0 + sx1) / 2.0
            head_width = max(subject_width * 0.72, subject_height * 0.22)
            head_height = max(subject_height * 0.34, head_width)
            bbox = [
                center_x - head_width / 2.0,
                sy0,
                center_x + head_width / 2.0,
                min(sy1, sy0 + head_height),
            ]

        identity_width, identity_height = self._CHARACTER_SHEET_IDENTITY_SIZE
        identity = self._isolate_reference_subject(
            image,
            bbox,
            identity_width,
            identity_height,
            margin=0.55,
        )
        source_name = str(source.get("name") or "character-reference") if isinstance(source, dict) else "character-reference"
        safe_stem = Path(source_name).stem[:64] or "character-reference"
        return self._image_to_payload(identity, f"{safe_stem}-identity-face.png")

    def _prepare_character_sheet_reference(
        self,
        source: Any,
        view: str,
        requested_framing: str,
    ) -> tuple[dict[str, str], str, dict[str, Any], int, int]:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet preprocessing requires Pillow.") from exc

        source_name = str(source.get("name") or "character-reference") if isinstance(source, dict) else "character-reference"
        _, image_bytes = base._decode_input_image(source)
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet source image could not be decoded: {exc}") from exc

        analysis = self._analyze_character_source(source)
        if requested_framing == "auto":
            resolved_framing = str(analysis.get("framing") or "source")
        else:
            resolved_framing = requested_framing
        if resolved_framing not in {"portrait", "full-body", "source"}:
            resolved_framing = "source"

        width, height = self._character_sheet_output_size(view, resolved_framing, image.size)
        crop_box = None
        margin = 0.0
        if bool(analysis.get("detected")):
            if view == "face-close-up":
                crop_box = analysis.get("faceBox") or analysis.get("subjectBox")
                margin = 0.55
            elif resolved_framing in {"portrait", "full-body"}:
                crop_box = analysis.get("subjectBox")
                margin = 0.14 if resolved_framing == "portrait" else 0.08

        prepared = image
        if isinstance(crop_box, (list, tuple)) and len(crop_box) == 4:
            prepared = self._isolate_reference_subject(image, crop_box, width, height, margin=margin)

        safe_stem = Path(source_name).stem[:64] or "character-reference"
        payload = self._image_to_payload(prepared, f"{safe_stem}-{view}-reference.png")
        enriched = dict(analysis)
        enriched["requestedFraming"] = requested_framing
        enriched["resolvedFraming"] = resolved_framing
        enriched["referenceSize"] = [prepared.width, prepared.height]
        enriched["outputSize"] = [width, height]
        enriched["referenceCropped"] = prepared.size != image.size or bool(crop_box)
        return payload, resolved_framing, enriched, width, height

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
            tasks = [item for item in policy.get("tasks", []) if isinstance(item, dict)]
            tasks = [item for item in tasks if item.get("id") != "character-sheet"]
            tasks.append({
                "id": "character-sheet",
                "label": "Character sheet",
                "referenceImages": 0,
                "masked": False,
                "sourceSizeOutput": False,
                "generationMode": "sequential",
                "identityMode": "face-plus-source",
                "identityReference": "auto-face-crop",
                "views": list(self._CHARACTER_SHEET_VIEWS),
                "framingModes": list(self._CHARACTER_SHEET_FRAMING_MODES),
                "defaultFraming": "auto",
                "compositeLayout": self._CHARACTER_SHEET_COMPOSITE_LAYOUT,
                "viewSizes": {
                    "face-close-up": {"width": self._CHARACTER_SHEET_FACE_SIZE[0], "height": self._CHARACTER_SHEET_FACE_SIZE[1]},
                    "portrait": {"width": self._CHARACTER_SHEET_PORTRAIT_SIZE[0], "height": self._CHARACTER_SHEET_PORTRAIT_SIZE[1]},
                    "full-body": {"width": self._CHARACTER_SHEET_FULL_BODY_SIZE[0], "height": self._CHARACTER_SHEET_FULL_BODY_SIZE[1]},
                },
            })
            policy["tasks"] = tasks
        return support

    def _persist_character_sheet_view_metadata(
        self,
        result: dict[str, Any],
        view: str,
        requested_framing: str,
        resolved_framing: str,
        width: int,
        height: int,
        analysis: dict[str, Any],
        identity_reference: bool = False,
    ) -> None:
        result["EditOperation"] = "character-sheet-view"
        result["CharacterSheetView"] = view
        result["CharacterSheetLabel"] = self._view_label(view)
        result["CharacterSheetRequestedFraming"] = requested_framing
        result["CharacterSheetSourceFraming"] = resolved_framing
        result["CharacterSheetWidth"] = width
        result["CharacterSheetHeight"] = height
        result["CharacterSheetReferenceCropped"] = bool(analysis.get("referenceCropped"))
        result["CharacterSheetSubjectDetected"] = bool(analysis.get("detected"))
        result["CharacterSheetIdentityMode"] = "face-plus-source"
        result["CharacterSheetIdentityReference"] = bool(identity_reference)

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
            record.update({
                "editOperation": "character-sheet-view",
                "characterSheetView": view,
                "characterSheetLabel": self._view_label(view),
                "characterSheetRequestedFraming": requested_framing,
                "characterSheetSourceFraming": resolved_framing,
                "characterSheetWidth": width,
                "characterSheetHeight": height,
                "characterSheetReferenceCropped": bool(analysis.get("referenceCropped")),
                "characterSheetSubjectDetected": bool(analysis.get("detected")),
                "characterSheetSubjectBox": analysis.get("subjectBox"),
                "characterSheetFaceBox": analysis.get("faceBox"),
                "characterSheetReferenceSize": analysis.get("referenceSize"),
                "characterSheetIdentityMode": "face-plus-source",
                "characterSheetIdentityReference": bool(identity_reference),
            })
            temporary = history_path.with_suffix(history_path.suffix + ".tmp-character-sheet")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(history_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise base.StableAmdBridgeError(
                f"Character sheet view completed, but Gallery metadata could not be updated: {exc}"
            ) from exc

    def _validated_character_sheet_output_path(self, raw_path: Any) -> Path:
        output_root = (self.repo_root / ".runtime" / "stableamd" / "output").resolve()
        path = Path(str(raw_path or "")).resolve()
        if output_root not in path.parents or not path.is_file():
            raise base.StableAmdBridgeError("Character Sheet child image is outside the StableAMD output folder or missing.")
        return path

    def _hide_character_sheet_child_history(self, items: list[dict[str, Any]], parent_prompt_id: str, parent_image_path: str) -> None:
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        for item in items:
            raw = str(item.get("HistoryPath") or item.get("historyPath") or "").strip()
            if not raw:
                continue
            path = Path(raw).resolve()
            if history_root not in path.parents or not path.is_file():
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(record, dict):
                    continue
                record["galleryHidden"] = True
                record["characterSheetParentPromptId"] = parent_prompt_id
                record["characterSheetParentImagePath"] = parent_image_path
                temporary = path.with_suffix(path.suffix + ".tmp-parent")
                temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue

    def compose_character_sheet(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet composition requires Pillow.") from exc

        items = request.get("items")
        if not isinstance(items, list) or len(items) != len(self._CHARACTER_SHEET_VIEWS):
            raise base.StableAmdBridgeError("Character Sheet composition requires exactly five generated views.")
        by_view: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise base.StableAmdBridgeError("Character Sheet item must be an object.")
            view = str(item.get("CharacterSheetView") or item.get("characterSheetView") or "").strip().lower()
            if view not in self._CHARACTER_SHEET_VIEWS or view in by_view:
                raise base.StableAmdBridgeError("Character Sheet composition received a missing or duplicate view.")
            by_view[view] = item
        ordered = [by_view[view] for view in self._CHARACTER_SHEET_VIEWS]

        tile_width = 896
        tile_height = 1152
        label_height = 64
        gutter = 32
        outer = 40
        canvas_width = outer * 2 + tile_width * 3 + gutter * 2
        canvas_height = outer * 2 + (tile_height + label_height) * 2 + gutter
        canvas = Image.new("RGB", (canvas_width, canvas_height), (244, 244, 242))
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.load_default(size=28)
        except TypeError:
            font = ImageFont.load_default()

        row1 = [outer + index * (tile_width + gutter) for index in range(3)]
        second_width = tile_width * 2 + gutter
        second_start = int(round((canvas_width - second_width) / 2.0))
        row2 = [second_start, second_start + tile_width + gutter]
        placements = [
            (row1[0], outer),
            (row1[1], outer),
            (row1[2], outer),
            (row2[0], outer + tile_height + label_height + gutter),
            (row2[1], outer + tile_height + label_height + gutter),
        ]

        sanitized_items: list[dict[str, Any]] = []
        for view, item, (left, top) in zip(self._CHARACTER_SHEET_VIEWS, ordered, placements):
            path = self._validated_character_sheet_output_path(item.get("ImagePath") or item.get("imagePath"))
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                scale = min(tile_width / image.width, tile_height / image.height)
                target = (
                    max(1, int(round(image.width * scale))),
                    max(1, int(round(image.height * scale))),
                )
                resized = image.resize(target, Image.Resampling.LANCZOS)
            x = left + (tile_width - resized.width) // 2
            y = top + (tile_height - resized.height) // 2
            canvas.paste(resized, (x, y))
            draw.rectangle((left, top, left + tile_width - 1, top + tile_height - 1), outline=(210, 210, 208), width=2)
            label = self._view_label(view)
            try:
                bounds = draw.textbbox((0, 0), label, font=font)
                text_width = bounds[2] - bounds[0]
                text_height = bounds[3] - bounds[1]
            except Exception:
                text_width, text_height = draw.textlength(label, font=font), 16
            draw.text(
                (left + (tile_width - text_width) / 2.0, top + tile_height + (label_height - text_height) / 2.0),
                label,
                fill=(32, 32, 32),
                font=font,
            )
            sanitized_items.append({
                "view": view,
                "label": label,
                "imagePath": str(path),
                "historyPath": str(item.get("HistoryPath") or item.get("historyPath") or ""),
                "width": item.get("Width") or item.get("width") or item.get("CharacterSheetWidth"),
                "height": item.get("Height") or item.get("height") or item.get("CharacterSheetHeight"),
                "sourceFraming": item.get("CharacterSheetSourceFraming") or item.get("characterSheetSourceFraming"),
                "identityReference": bool(item.get("CharacterSheetIdentityReference") or item.get("characterSheetIdentityReference")),
            })

        output_root = (self.repo_root / ".runtime" / "stableamd" / "output").resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        prompt_id = uuid.uuid4().hex
        image_path = output_root / f"StableAMD_CHARACTER_SHEET_{prompt_id}.png"
        canvas.save(image_path, format="PNG", optimize=True)

        first = ordered[0]
        generation_seconds = 0.0
        for item in ordered:
            try:
                generation_seconds += float(item.get("GenerationSeconds") or item.get("generationSeconds") or 0.0)
            except (TypeError, ValueError):
                pass
        prompt = str(request.get("prompt") or "").strip() or self._CHARACTER_SHEET_DEFAULT_PROMPT
        requested_framing = str(request.get("requestedFraming") or "auto")
        source_framing = str(request.get("sourceFraming") or "source")
        created_at = datetime.now(timezone.utc).isoformat()
        shared_seed = first.get("Seed") if "Seed" in first else first.get("seed")
        record = {
            "schemaVersion": 3,
            "createdAtUtc": created_at,
            "promptId": prompt_id,
            "mode": "character-sheet",
            "editOperation": "character-sheet",
            "prompt": prompt,
            "negativePrompt": "",
            "modelId": str(first.get("ModelId") or first.get("modelId") or ""),
            "modelName": str(first.get("ModelName") or first.get("modelName") or "Krea 2 Turbo"),
            "width": canvas_width,
            "height": canvas_height,
            "seed": shared_seed,
            "generationSeconds": round(generation_seconds, 3),
            "imagePath": str(image_path),
            "characterSheetLayout": self._CHARACTER_SHEET_COMPOSITE_LAYOUT,
            "characterSheetViews": list(self._CHARACTER_SHEET_VIEWS),
            "characterSheetRequestedFraming": requested_framing,
            "characterSheetSourceFraming": source_framing,
            "characterSheetIdentityMode": "face-plus-source",
            "characterSheetItems": sanitized_items,
            "galleryHidden": False,
        }
        history_path = self._save_bundle_history(record)
        self._hide_character_sheet_child_history(ordered, prompt_id, str(image_path))

        composite = {
            "ImagePath": str(image_path),
            "Width": canvas_width,
            "Height": canvas_height,
            "Layout": self._CHARACTER_SHEET_COMPOSITE_LAYOUT,
        }
        return {
            "PromptId": prompt_id,
            "Mode": "character-sheet",
            "EditOperation": "character-sheet",
            "Prompt": prompt,
            "NegativePrompt": "",
            "ModelId": record["modelId"],
            "ModelName": record["modelName"],
            "Width": canvas_width,
            "Height": canvas_height,
            "Seed": shared_seed,
            "GenerationSeconds": record["generationSeconds"],
            "ImagePath": str(image_path),
            "HistoryPath": str(history_path),
            "CharacterSheetLayout": self._CHARACTER_SHEET_COMPOSITE_LAYOUT,
            "CharacterSheetViews": list(self._CHARACTER_SHEET_VIEWS),
            "CharacterSheetRequestedFraming": requested_framing,
            "CharacterSheetSourceFraming": source_framing,
            "CharacterSheetIdentityMode": "face-plus-source",
            "CharacterSheetItems": ordered,
            "CharacterSheetComposite": composite,
        }

    def history(self, limit: int = 0) -> Any:
        records = super().history(limit=0)
        values = records if isinstance(records, list) else ([records] if records else [])
        visible = [record for record in values if not (isinstance(record, dict) and bool(record.get("galleryHidden")))]
        return visible[:limit] if limit > 0 else visible

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
                "Character sheet uses managed source/identity references and does not accept extra user references."
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
        requested_framing = str(request.get("characterSheetFraming") or "auto").strip().lower()
        if requested_framing not in self._CHARACTER_SHEET_FRAMING_MODES:
            raise base.StableAmdBridgeError("Character sheet framing must be auto, portrait, or full-body.")

        source = request.get("inputImage")
        source_name = str(source.get("name") or "source-image") if isinstance(source, dict) else "source-image"
        prepared_source, resolved_framing, analysis, width, height = self._prepare_character_sheet_reference(
            source,
            view,
            requested_framing,
        )
        identity_payload = None
        if view != "face-close-up":
            identity_payload = self._prepare_character_sheet_identity_reference(source, analysis)

        staged = base.stage_input_image(self.repo_root, prepared_source)
        staged_identity = None
        if identity_payload is not None:
            staged_identity = base.stage_input_image(self.repo_root, identity_payload)

        clean = dict(request)
        clean["mode"] = "txt2img"
        clean["prompt"] = self._build_character_sheet_instruction(
            view,
            str(request.get("prompt") or ""),
            resolved_framing,
        )
        clean["width"] = width
        clean["height"] = height
        clean.pop("inputImage", None)
        clean.pop("denoise", None)
        clean.pop("control", None)
        clean.pop("references", None)
        clean.pop("editTask", None)
        clean.pop("characterSheetView", None)
        clean.pop("characterSheetFraming", None)

        internal_references = []
        if staged_identity is not None:
            internal_references.append({"name": staged_identity.name, "role": "content"})
        self._stableamd_krea_edit_context.value = {
            "image_name": staged.name,
            "source_name": source_name,
            "references": internal_references,
            "output_size": {"width": width, "height": height},
        }
        try:
            result = self._generate_krea2_turbo(clean, selected)
        finally:
            self._stableamd_krea_edit_context.value = None
            staged.unlink(missing_ok=True)
            if staged_identity is not None:
                staged_identity.unlink(missing_ok=True)

        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Krea 2 Character Sheet provider did not return a result object.")
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
            identity_reference=staged_identity is not None,
        )
        return result
