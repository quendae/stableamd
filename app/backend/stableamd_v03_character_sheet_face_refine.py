from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import stableamd_v03_character_sheet_v2 as sheetv2

base = sheetv2.base

_TIGHT_FACE_PROMPT = (
    "Perform a conservative identity-only correction on image A using image B as the authoritative original face "
    "reference. Preserve image A's camera angle, head rotation, gaze direction, expression class, lighting, hair "
    "placement and surrounding composition; do not rotate the head toward image B. Match the source person's exact "
    "age impression and youthful or mature facial proportions as shown in image B. Preserve face width and length, "
    "forehead proportions, eye spacing and eye shape, eyelids, eyebrows, nose length, width, bridge and tip, mouth "
    "width and lip shape, cheek fullness, jaw width and jaw curve, chin shape, ears, hairline, skin texture and natural "
    "asymmetries. Do not make the person older or younger. Do not beautify, glamorize, idealize, slim the face, enlarge "
    "the eyes, sharpen the jaw, narrow the nose, smooth away distinctive features, or replace the face with a generic "
    "studio portrait. Keep the same person. Correct only the visible facial/head identity inside this crop."
)


class CharacterSheetV2FaceRefineBridgeMixin:
    """Second-stage identity correction for the most identity-sensitive v2 panels.

    The normal v2 detailer remains the broad head/hair correction pass. This
    layer then performs a smaller, higher-resolution face-only correction for
    FACE, FRONT and THREE_QUARTER. SIDE intentionally stays on the broad pass:
    forcing a frontal source face into a strict profile tends to rotate or flatten
    the profile rather than improve likeness.
    """

    _TIGHT_FACE_ROLES = {"face", "front", "three-quarter"}
    _TIGHT_FACE_REFERENCE_SIZE = (768, 768)
    _HEAD_REFERENCE_SIZE = (768, 896)

    @classmethod
    def _should_tight_face_refine(cls, role: str) -> bool:
        return str(role or "").strip().lower() in cls._TIGHT_FACE_ROLES

    @staticmethod
    def _tight_face_identity_prompt(role: str) -> str:
        normalized = str(role or "").strip().lower()
        if normalized == "three-quarter":
            return _TIGHT_FACE_PROMPT + " Preserve the existing three-quarter rotation exactly."
        if normalized == "face":
            return _TIGHT_FACE_PROMPT + " Preserve the existing close-up framing exactly."
        return _TIGHT_FACE_PROMPT

    @staticmethod
    def _valid_face_box(analysis: Any) -> list[float] | None:
        face_box = analysis.get("faceBox") if isinstance(analysis, dict) else None
        if not isinstance(face_box, (list, tuple)) or len(face_box) != 4:
            return None
        try:
            values = [float(value) for value in face_box]
        except (TypeError, ValueError):
            return None
        if values[2] <= values[0] or values[3] <= values[1]:
            return None
        return values

    def _load_identity_source_image(self, source: dict[str, Any]) -> Any:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet face refinement requires Pillow.") from exc
        _, image_bytes = base._decode_input_image(source)
        try:
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet identity source could not be decoded: {exc}") from exc

    def _prepare_v2_head_identity(
        self,
        source: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, str] | None:
        face_box = self._valid_face_box(analysis)
        if face_box is None:
            return None
        image = self._load_identity_source_image(source)
        x0, y0, x1, y1 = face_box
        face_width = x1 - x0
        face_height = y1 - y0
        center_x = (x0 + x1) / 2.0
        # Wider and substantially deeper than the base identity crop. It keeps
        # hair silhouette, ears, neck and shoulders/collar so the first detail
        # pass has structural context without reintroducing scene background.
        head_box = [
            center_x - face_width * 1.35,
            y0 - face_height * 0.80,
            center_x + face_width * 1.35,
            y1 + face_height * 2.15,
        ]
        width, height = self._HEAD_REFERENCE_SIZE
        prepared = self._isolate_reference_subject(image, head_box, width, height, margin=0.02)
        source_name = str(source.get("name") or "character-reference")
        safe_stem = Path(source_name).stem[:64] or "character-reference"
        return self._image_to_payload(prepared, f"{safe_stem}-identity-head-shoulders.png")

    def _prepare_v2_tight_identity(
        self,
        source: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, str] | None:
        face_box = self._valid_face_box(analysis)
        if face_box is None:
            return None
        image = self._load_identity_source_image(source)
        width, height = self._TIGHT_FACE_REFERENCE_SIZE
        prepared = self._isolate_reference_subject(image, face_box, width, height, margin=0.18)
        source_name = str(source.get("name") or "character-reference")
        safe_stem = Path(source_name).stem[:64] or "character-reference"
        return self._image_to_payload(prepared, f"{safe_stem}-identity-tight-face.png")

    def _prepare_v2_detail_context(
        self,
        panel: sheetv2.CharacterSheetV2Panel,
        source: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Upgrade the broad first detail pass from face-only to head/shoulders identity."""
        context = super()._prepare_v2_detail_context(panel, source)
        if context is None:
            return None
        source_analysis = self._analyze_character_source(source)
        payload = self._prepare_v2_head_identity(source, source_analysis)
        if payload is None:
            return context
        try:
            staged = self._stage_character_sheet_v2_source(payload)
        except (OSError, base.StableAmdBridgeError):
            return context
        previous = context.get("identity")
        context["identity"] = staged
        context["identityMode"] = "head-shoulders"
        if previous is not None and hasattr(previous, "unlink"):
            previous.unlink(missing_ok=True)
        return context

    @staticmethod
    def _tight_face_detail_box(
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
        if panel_width < 16 or panel_height < 16 or x1 <= x0 or y1 <= y0:
            return None

        face_width = x1 - x0
        face_height = y1 - y0
        center_x = (x0 + x1) / 2.0
        center_y = (y0 + y1) / 2.0
        desired_width = max(64, int(round((face_width * 1.45) / 16.0)) * 16)
        desired_height = max(64, int(round((face_height * 1.65) / 16.0)) * 16)
        max_width = panel_width - (panel_width % 16)
        max_height = panel_height - (panel_height % 16)
        desired_width = min(max_width, desired_width)
        desired_height = min(max_height, desired_height)
        if desired_width < 16 or desired_height < 16:
            return None

        left = int(round(center_x - desired_width / 2.0))
        top = int(round(center_y - desired_height / 2.0))
        left = max(0, min(left, panel_width - desired_width))
        top = max(0, min(top, panel_height - desired_height))
        return left, top, left + desired_width, top + desired_height

    @staticmethod
    def _tight_face_render_size(crop_box: tuple[int, int, int, int]) -> tuple[int, int]:
        crop_width = max(16, int(crop_box[2]) - int(crop_box[0]))
        crop_height = max(16, int(crop_box[3]) - int(crop_box[1]))
        ratio = crop_width / crop_height
        if ratio >= 1.0:
            height = 512
            width = min(768, max(512, int(round((height * ratio) / 16.0)) * 16))
        else:
            width = 512
            height = min(768, max(512, int(round((width / ratio) / 16.0)) * 16))
        return width, height

    def _prepare_v2_tight_detail_context(
        self,
        panel: sheetv2.CharacterSheetV2Panel,
        first_path: Any,
        source: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            from PIL import Image
        except Exception as exc:
            raise base.StableAmdBridgeError("Character Sheet tight face refinement requires Pillow.") from exc

        first = Path(str(first_path)).resolve()
        try:
            with Image.open(first) as opened:
                panel_image = opened.convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Character Sheet refined panel could not be decoded: {exc}") from exc

        analysis_payload = self._image_to_payload(panel_image, f"{panel.role}-tight-face-analysis.png")
        analysis = self._analyze_character_source(analysis_payload)
        face_box = self._valid_face_box(analysis)
        if face_box is None:
            return None
        crop_box = self._tight_face_detail_box(face_box, panel_image.size)
        if crop_box is None:
            return None

        source_analysis = self._analyze_character_source(source)
        identity_payload = self._prepare_v2_tight_identity(source, source_analysis)
        if identity_payload is None:
            return None

        scene_crop = panel_image.crop(crop_box)
        scene_payload = self._image_to_payload(scene_crop, f"{panel.role}-generated-tight-face.png")
        scene = self._stage_character_sheet_v2_source(scene_payload)
        identity_staged: Path | None = None
        try:
            identity_staged = self._stage_character_sheet_v2_source(identity_payload)
        except Exception:
            scene.unlink(missing_ok=True)
            raise
        width, height = self._tight_face_render_size(crop_box)
        return {
            "scene": scene,
            "identity": identity_staged,
            "cropBox": crop_box,
            "width": width,
            "height": height,
        }

    def _stitch_v2_tight_detail_result(
        self,
        panel: sheetv2.CharacterSheetV2Panel,
        first_path: Any,
        refined_path: Any,
        crop_box: tuple[int, int, int, int],
    ) -> Path:
        first_panel = sheetv2.CharacterSheetV2Panel(
            role=panel.role,
            index=panel.index,
            path=Path(str(first_path)).resolve(),
            box=panel.box,
            detail_box=panel.detail_box,
        )
        return super()._stitch_v2_detail_result(first_panel, refined_path, crop_box)

    @staticmethod
    def _seconds(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _refine_v2_panel(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        panel: sheetv2.CharacterSheetV2Panel,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        first = super()._refine_v2_panel(request, model, panel, source)
        result = dict(first)
        role = str(panel.role or "").strip().lower()

        if not self._should_tight_face_refine(role):
            result["faceIdentityStatus"] = "skipped"
            result["faceIdentitySkipped"] = "profile-view" if role == "side" else "back-view"
            return result
        if str(result.get("detailerStatus") or "") != "completed":
            result["faceIdentityStatus"] = "skipped"
            result["faceIdentitySkipped"] = "first-pass-not-completed"
            return result

        first_path = result.get("path") or panel.path
        try:
            context = self._prepare_v2_tight_detail_context(panel, first_path, source)
        except (OSError, base.StableAmdBridgeError) as exc:
            result["faceIdentityStatus"] = "skipped"
            result["faceIdentitySkipped"] = "preprocess-failed"
            result["faceIdentityError"] = str(exc)
            return result
        if context is None:
            result["faceIdentityStatus"] = "skipped"
            result["faceIdentitySkipped"] = "no-face"
            return result

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
                prompt=self._tight_face_identity_prompt(role),
                width=context["width"],
                height=context["height"],
            )
            refined_path = refined.get("ImagePath") if isinstance(refined, dict) else None
            if not refined_path:
                raise base.StableAmdBridgeError("Tight face Identity Edit did not return an image path.")
            stitched_path = self._stitch_v2_tight_detail_result(
                panel,
                first_path,
                refined_path,
                context["cropBox"],
            )
            result.update({
                "path": stitched_path,
                "faceIdentityStatus": "completed",
                "faceIdentitySkipped": None,
                "faceIdentityPromptId": refined.get("PromptId"),
                "faceIdentityHistoryPath": refined.get("HistoryPath"),
                "faceIdentityGenerationSeconds": self._seconds(refined.get("GenerationSeconds")),
                "faceIdentityCropBox": list(context["cropBox"]),
                "detailerGenerationSeconds": self._seconds(result.get("detailerGenerationSeconds"))
                + self._seconds(refined.get("GenerationSeconds")),
            })
            return result
        except (OSError, base.StableAmdBridgeError) as exc:
            result["faceIdentityStatus"] = "skipped"
            result["faceIdentitySkipped"] = "generation-failed"
            result["faceIdentityError"] = str(exc)
            return result
        finally:
            if attempted:
                release = getattr(self, "_release_character_sheet_runtime", None)
                if callable(release):
                    release()
            scene.unlink(missing_ok=True)
            identity_reference.unlink(missing_ok=True)

    def _hide_character_sheet_v2_intermediates(
        self,
        base_result: dict[str, Any],
        detail_results: list[dict[str, Any]],
        final_result: dict[str, Any],
    ) -> None:
        super()._hide_character_sheet_v2_intermediates(base_result, detail_results, final_result)
        hider = getattr(self, "_hide_character_sheet_child_history", None)
        if not callable(hider):
            return
        extra = [
            {"HistoryPath": str(item.get("faceIdentityHistoryPath") or "")}
            for item in detail_results
            if str(item.get("faceIdentityHistoryPath") or "").strip()
        ]
        if extra:
            hider(
                extra,
                str(final_result.get("PromptId") or ""),
                str(final_result.get("ImagePath") or ""),
            )
