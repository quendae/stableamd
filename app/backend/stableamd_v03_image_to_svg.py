from __future__ import annotations

import base64
import io
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Sequence

import stableamd_server as base
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

import stableamd_v03_svg_sanitize as svg_sanitize
import stableamd_v03_vector as vector

IMAGE_TO_SVG_VERSION = "image-to-svg-v1"
IMAGE_TO_SVG_MODES = {"artwork", "photo-direct", "photo-stylized"}
IMAGE_TO_SVG_STYLIZATIONS = {"preserve", "creative"}
IMAGE_TO_SVG_DETAILS = {"simple", "medium", "detailed"}
IMAGE_TO_SVG_COLORS = {2, 4, 8, 16}
IMAGE_TO_SVG_BACKGROUNDS = {"preserve", "transparent"}
IMAGE_TO_SVG_CROPS = {"preserve", "auto", "manual"}
IMAGE_TO_SVG_SOURCE_KINDS = {"upload", "gallery", "current"}
ADVANCED_DEFAULTS = {
    "smoothing": 20,
    "edgeStrength": 70,
    "denoise": 10,
    "posterize": 20,
    "backgroundTolerance": 18,
}
MODE_PRESETS = {
    ("artwork", None): {"smoothing": 20, "edgeStrength": 70, "denoise": 10, "posterize": 20},
    ("photo-direct", None): {"smoothing": 35, "edgeStrength": 55, "denoise": 35, "posterize": 45},
    ("photo-stylized", "preserve"): {"smoothing": 55, "edgeStrength": 65, "denoise": 50, "posterize": 70},
    ("photo-stylized", "creative"): {"smoothing": 30, "edgeStrength": 60, "denoise": 20, "posterize": 35},
}
_SOURCE_FIELDS = {"kind", "id", "image"}
_REQUEST_FIELDS = {
    "source", "mode", "stylization", "detail", "colors", "background",
    "cropMode", "crop", "advanced",
}
_ADVANCED_FIELDS = set(ADVANCED_DEFAULTS)


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _bounded_number(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric.")
    if value < 0 or value > 100:
        raise ValueError(f"{field} must be between 0 and 100.")
    return int(round(value))


def _validate_colors(value: Any) -> int | str:
    if value is None or value == "auto":
        return "auto"
    if isinstance(value, bool) or not isinstance(value, int) or value not in IMAGE_TO_SVG_COLORS:
        raise ValueError("Image-to-SVG colors must be auto, 2, 4, 8, or 16.")
    return value


def mode_preset(mode: str, stylization: str | None = None) -> dict[str, int]:
    key = (mode, stylization if mode == "photo-stylized" else None)
    return dict(MODE_PRESETS.get(key, MODE_PRESETS[("artwork", None)]))


def validate_crop(crop: Any, width: int, height: int) -> dict[str, int]:
    if not isinstance(crop, dict):
        raise ValueError("crop must be an object.")
    if set(crop) != {"x", "y", "width", "height"}:
        raise ValueError("crop must contain only x, y, width, and height.")
    values: dict[str, int] = {}
    for field in ("x", "y", "width", "height"):
        value = crop[field]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"crop {field} must be an integer.")
        values[field] = value
    if values["x"] < 0 or values["y"] < 0 or values["width"] <= 0 or values["height"] <= 0:
        raise ValueError("crop coordinates and dimensions must be positive.")
    if values["x"] + values["width"] > width or values["y"] + values["height"] > height:
        raise ValueError("crop must stay fully inside the source image.")
    return values


def validate_image_to_svg_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Image-to-SVG request must be a JSON object.")
    unsupported = sorted(set(payload) - _REQUEST_FIELDS)
    if unsupported:
        raise ValueError("Unsupported Image-to-SVG field(s): " + ", ".join(unsupported))

    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValueError("source must be an object.")
    unsupported_source = sorted(set(source) - _SOURCE_FIELDS)
    if unsupported_source:
        raise ValueError("Unsupported Image-to-SVG source field(s): " + ", ".join(unsupported_source))
    kind = _required_text(source.get("kind"), "source.kind").lower()
    if kind not in IMAGE_TO_SVG_SOURCE_KINDS:
        raise ValueError("source.kind must be upload, gallery, or current.")

    clean_source: dict[str, Any] = {"kind": kind}
    if kind == "upload":
        image = source.get("image")
        if image is None:
            raise ValueError("upload source requires source.image.")
        # Reuse the hardened existing image payload contract without staging it yet.
        base._decode_input_image(image)
        clean_source["image"] = image
    else:
        clean_source["id"] = _required_text(source.get("id"), f"source.{kind}.id")
        if "/" in clean_source["id"] or "\\" in clean_source["id"] or clean_source["id"] in {".", ".."}:
            raise ValueError("source id must be a managed record identifier.")

    mode = str(payload.get("mode", "artwork")).strip().lower()
    if mode not in IMAGE_TO_SVG_MODES:
        raise ValueError("Image-to-SVG mode must be artwork, photo-direct, or photo-stylized.")

    stylization = payload.get("stylization")
    if mode == "photo-stylized":
        stylization = "preserve" if stylization is None else str(stylization).strip().lower()
        if stylization not in IMAGE_TO_SVG_STYLIZATIONS:
            raise ValueError("photo-stylized requires stylization preserve or creative.")
    elif stylization is not None:
        raise ValueError("stylization is valid only for photo-stylized mode.")

    detail = str(payload.get("detail", "medium")).strip().lower()
    if detail not in IMAGE_TO_SVG_DETAILS:
        raise ValueError("Image-to-SVG detail must be simple, medium, or detailed.")

    colors = _validate_colors(payload.get("colors", "auto"))

    background = str(payload.get("background", "preserve")).strip().lower()
    if background not in IMAGE_TO_SVG_BACKGROUNDS:
        raise ValueError("Image-to-SVG background must be preserve or transparent.")

    crop_mode = str(payload.get("cropMode", "preserve")).strip().lower()
    if crop_mode not in IMAGE_TO_SVG_CROPS:
        raise ValueError("Image-to-SVG cropMode must be preserve, auto, or manual.")
    crop = payload.get("crop")
    if crop_mode == "manual":
        if crop is None:
            raise ValueError("manual cropMode requires crop.")
    elif crop is not None:
        raise ValueError("crop is valid only when cropMode is manual.")

    advanced_raw = payload.get("advanced", {})
    if not isinstance(advanced_raw, dict):
        raise ValueError("advanced must be an object.")
    unsupported_advanced = sorted(set(advanced_raw) - _ADVANCED_FIELDS)
    if unsupported_advanced:
        raise ValueError("Unsupported Image-to-SVG advanced field(s): " + ", ".join(unsupported_advanced))
    preset = mode_preset(mode, stylization)
    advanced = dict(ADVANCED_DEFAULTS)
    advanced.update(preset)
    for field, value in advanced_raw.items():
        if field == "backgroundTolerance":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 255:
                raise ValueError("backgroundTolerance must be an integer between 0 and 255.")
            advanced[field] = value
        else:
            advanced[field] = _bounded_number(value, field)

    return {
        "source": clean_source,
        "mode": mode,
        "stylization": stylization,
        "detail": detail,
        "colors": colors,
        "background": background,
        "cropMode": crop_mode,
        "crop": crop,
        "advanced": advanced,
    }


def border_background_mask(
    pixels: Sequence[Sequence[int]], width: int, height: int, tolerance: int = 18
) -> set[int]:
    return vector._border_connected_background_mask(pixels, width, height, tolerance=tolerance)


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    minimum, maximum = alpha.getextrema()
    if minimum == 255 and maximum == 255:
        return None
    return alpha.getbbox()


def _background_bbox(image: Image.Image, tolerance: int) -> tuple[int, int, int, int] | None:
    rgba = image.convert("RGBA")
    pixels = list(rgba.getdata())
    mask = border_background_mask(
        [(p[0], p[1], p[2]) for p in pixels],
        rgba.width,
        rgba.height,
        tolerance=tolerance,
    )
    if not mask:
        return (0, 0, rgba.width, rgba.height)
    keep = [index for index in range(rgba.width * rgba.height) if index not in mask and rgba.getdata()[index][3] > 0]
    if not keep:
        return None
    xs = [index % rgba.width for index in keep]
    ys = [index // rgba.width for index in keep]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _apply_crop(image: Image.Image, crop_mode: str, crop: dict[str, int] | None, tolerance: int) -> Image.Image:
    if crop_mode == "preserve":
        return image
    if crop_mode == "manual":
        if crop is None:
            raise ValueError("manual crop requires crop coordinates.")
        validated = validate_crop(crop, image.width, image.height)
        return image.crop((
            validated["x"], validated["y"],
            validated["x"] + validated["width"],
            validated["y"] + validated["height"],
        ))
    bbox = _alpha_bbox(image)
    if bbox is None:
        bbox = _background_bbox(image, tolerance)
    if bbox is None:
        return image
    return image.crop(bbox)


def _posterize(image: Image.Image, amount: int, colors: int | str) -> Image.Image:
    if amount <= 0 and colors == "auto":
        return image
    levels = max(2, min(256, int(round(256 - (amount * 2.2)))))
    rgb = image.convert("RGB")
    rgb = ImageOps.posterize(rgb, max(1, min(8, round(levels.bit_length() - 1))))
    if colors != "auto":
        rgb = rgb.quantize(colors=int(colors), method=Image.Quantize.MEDIANCUT).convert("RGB")
    if "A" in image.getbands():
        return Image.merge("RGBA", (*rgb.split(), image.getchannel("A")))
    return rgb.convert("RGBA")


def _resize_for_detail(image: Image.Image, detail: str) -> Image.Image:
    max_dim = {"simple": 1536, "medium": 2048, "detailed": 3072}[detail]
    if max(image.size) <= max_dim:
        return image
    scale = max_dim / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def preprocess_image_to_svg(
    source_path: Path,
    destination_path: Path,
    *,
    mode: str,
    stylization: str | None,
    detail: str,
    colors: int | str,
    background: str,
    crop_mode: str,
    crop: dict[str, int] | None,
    advanced: dict[str, Any],
) -> Path:
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if not source.is_file():
        raise base.StableAmdBridgeError("Image-to-SVG source image was not found.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}")
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
        image = _apply_crop(image, crop_mode, crop, int(advanced["backgroundTolerance"]))

        denoise = int(advanced["denoise"])
        smoothing = int(advanced["smoothing"])
        edge_strength = int(advanced["edgeStrength"])
        posterize = int(advanced["posterize"])

        if denoise > 0:
            radius = 1 if denoise < 50 else 2
            image = image.filter(ImageFilter.MedianFilter(size=3 if radius == 1 else 5))
        if smoothing > 0:
            radius = max(0.1, smoothing / 40)
            image = image.filter(ImageFilter.GaussianBlur(radius=radius))
        if edge_strength > 0:
            image = ImageEnhance.Sharpness(image).enhance(1.0 + edge_strength / 100)
        if mode != "artwork" or posterize > 0 or colors != "auto":
            image = _posterize(image, posterize, colors)

        image = _resize_for_detail(image, detail)

        if background == "transparent":
            rgba = image.convert("RGBA")
            pixels = list(rgba.getdata())
            mask = border_background_mask(
                [(p[0], p[1], p[2]) for p in pixels],
                rgba.width,
                rgba.height,
                tolerance=int(advanced["backgroundTolerance"]),
            )
            updated = list(pixels)
            for index in mask:
                red, green, blue, _alpha = updated[index]
                updated[index] = (red, green, blue, 0)
            image = Image.new("RGBA", rgba.size)
            image.putdata(updated)

        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(destination)
    except base.StableAmdBridgeError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise base.StableAmdBridgeError(f"Image-to-SVG preprocessing failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _history_records(repo_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    root = (Path(repo_root).resolve() / ".runtime" / "stableamd" / "history").resolve()
    if not root.is_dir():
        return []
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append((path.resolve(), record))
    return records


def resolve_managed_source(repo_root: Path, source: dict[str, Any]) -> tuple[Path, bool, str]:
    kind = str(source.get("kind") or "").lower()
    if kind == "upload":
        staged = base.stage_input_image(repo_root, source["image"])
        return staged, True, "upload"

    source_id = _required_text(source.get("id"), f"source.{kind}.id")
    for _history_path, record in _history_records(repo_root):
        prompt_id = str(record.get("promptId") or record.get("PromptId") or "").strip()
        if prompt_id != source_id:
            continue
        raw = str(record.get("imagePath") or record.get("ImagePath") or "").strip()
        if not raw:
            continue
        try:
            path = base.resolve_output_image(repo_root, raw)
        except ValueError:
            continue
        if kind == "gallery" and str(record.get("assetType") or "").lower() == "svg":
            raise base.StableAmdBridgeError("An SVG Gallery asset cannot be used as an Image-to-SVG raster source.")
        return path, False, kind
    raise base.StableAmdBridgeError(f"Managed {kind} source '{source_id}' was not found.")


def _image_payload_from_path(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    mime = "image/png"
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    return {
        "name": path.name,
        "mimeType": mime,
        "dataBase64": base64.b64encode(data).decode("ascii"),
    }


def _select_krea_model(bridge: Any) -> dict[str, Any]:
    for model in bridge.models():
        if not isinstance(model, dict):
            continue
        family = str(model.get("family") or model.get("Family") or "").lower()
        asset_mode = str(model.get("assetMode") or model.get("AssetMode") or "").lower()
        if family == "krea2" and asset_mode == "bundle":
            return model
    raise base.StableAmdBridgeError("Photo Stylized / Creative requires an installed Krea 2 Turbo model.")


def _creative_prompt(request: dict[str, Any]) -> str:
    detail = request["detail"]
    colors = request["colors"]
    palette = "a restrained coherent palette" if colors == "auto" else f"a maximum palette of {colors} colors"
    detail_text = {
        "simple": "very simple broad shapes",
        "medium": "balanced clean vector-like shapes",
        "detailed": "richer but still intentional flat shapes",
    }[detail]
    return (
        "Transform the source image into a clean flat vector-style illustration while preserving the main subject, "
        "composition, pose, identity and broad object placement. Use solid regions, crisp edges, "
        f"{detail_text}, and {palette}. Remove photographic texture, blur, gradients, reflections and noise. "
        "Do not add text, letters, numbers, logos or watermarks."
    )


class ImageToSvgBridgeMixin:
    _image_to_svg_lock = RLock()

    def _resolve_image_to_svg_source(self, source: dict[str, Any]) -> tuple[Path, bool, str]:
        return resolve_managed_source(self.repo_root, source)

    def _creative_vector_raster(self, request: dict[str, Any], source_path: Path) -> tuple[Path, float, dict[str, Any]]:
        model = _select_krea_model(self)
        started = time.monotonic()
        result = self.generate({
            "mode": "img2img",
            "modelId": str(model.get("id") or model.get("Id") or ""),
            "prompt": _creative_prompt(request),
            "inputImage": _image_payload_from_path(source_path),
            "width": 1024,
            "height": 1024,
            "steps": 8,
            "cfg": 1.0,
            "samplerName": "euler",
            "scheduler": "simple",
            "startBackendIfNeeded": True,
        })
        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Krea Creative preprocessing did not return a result.")
        output = base.resolve_output_image(
            self.repo_root,
            str(result.get("ImagePath") or result.get("imagePath") or ""),
        )
        return output, round(time.monotonic() - started, 3), result

    def image_to_svg(self, request: dict[str, Any]) -> dict[str, Any]:
        clean = validate_image_to_svg_request(request)
        source_path, source_owned, source_kind = self._resolve_image_to_svg_source(clean["source"])
        started_total = time.monotonic()
        creative_result: dict[str, Any] | None = None
        creative_seconds = 0.0
        working_source = source_path
        prepared_path: Path | None = None
        raw_svg_path: Path | None = None
        svg_path: Path | None = None
        preview_path: Path | None = None
        persisted = False
        token = uuid.uuid4().hex
        prompt_id = f"image-vector-{token}"
        vector_root = (Path(self.repo_root).resolve() / ".runtime" / "stableamd" / "output" / "vector").resolve()
        vector_root.mkdir(parents=True, exist_ok=True)
        prepared_path = vector_root / f"{prompt_id}.prepared.png"
        raw_svg_path = vector_root / f"{prompt_id}.raw.svg"
        svg_path = vector_root / f"{prompt_id}.svg"
        preview_path = vector_root / f"{prompt_id}-preview.png"
        vector_started = time.monotonic()

        try:
            if clean["mode"] == "photo-stylized" and clean["stylization"] == "creative":
                lock = getattr(self, "_generation_run_lock", None)
                if lock is None:
                    raise base.StableAmdBridgeError("Creative Image-to-SVG requires the generation serialization lock.")
                with lock:
                    working_source, creative_seconds, creative_result = self._creative_vector_raster(clean, source_path)

            preprocess_image_to_svg(
                working_source,
                prepared_path,
                mode=clean["mode"],
                stylization=clean["stylization"],
                detail=clean["detail"],
                colors=clean["colors"],
                background=clean["background"],
                crop_mode=clean["cropMode"],
                crop=clean["crop"],
                advanced=clean["advanced"],
            )

            vector_request = {
                "detail": clean["detail"],
                "colors": clean["colors"],
            }
            self._run_vectorizer(prepared_path, raw_svg_path, vector_request)
            sanitized = self._sanitize_vector_svg(raw_svg_path)
            temp_svg = svg_path.with_suffix(".svg.tmp")
            temp_svg.write_text(sanitized.xml, encoding="utf-8")
            temp_svg.replace(svg_path)
            self._render_vector_preview(sanitized.xml, preview_path)
            vector_seconds = round(time.monotonic() - vector_started, 3)

            source_dimensions = None
            try:
                with Image.open(source_path) as image:
                    source_dimensions = [int(image.width), int(image.height)]
            except (OSError, ValueError):
                source_dimensions = None

            record = {
                "schemaVersion": 3,
                "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "promptId": prompt_id,
                "mode": "vector",
                "assetType": "svg",
                "workflow": IMAGE_TO_SVG_VERSION,
                "provider": "krea2-vtrace" if creative_result else "image-vtrace",
                "sourceKind": source_kind,
                "sourceRecordId": clean["source"].get("id"),
                "sourceWidth": source_dimensions[0] if source_dimensions else None,
                "sourceHeight": source_dimensions[1] if source_dimensions else None,
                "modeName": clean["mode"],
                "stylization": clean["stylization"],
                "detail": clean["detail"],
                "colors": clean["colors"],
                "background": clean["background"],
                "cropMode": clean["cropMode"],
                "crop": clean["crop"],
                "advanced": clean["advanced"],
                "creativeProvider": "krea2-ostris-edit" if creative_result else None,
                "creativeModelId": str((creative_result or {}).get("ModelId") or "") or None,
                "creativeSeconds": creative_seconds,
                "vectorizerVersion": vector.vectorizer.VTRACER_VERSION,
                "sanitizerVersion": svg_sanitize.SANITIZER_VERSION,
                "svgPath": str(svg_path),
                "previewPath": str(preview_path),
                "imagePath": str(preview_path),
                "width": sanitized.width,
                "height": sanitized.height,
                "pathCount": sanitized.path_count,
                "nodeCount": sanitized.node_count,
                "sanitized": True,
                "sourcePath": str(source_path) if source_kind == "upload" else None,
                "creativeRasterPath": str(working_source) if creative_result else None,
                "ownedIntermediatePaths": [str(prepared_path)],
                "vectorizationSeconds": vector_seconds,
                "totalSeconds": round(time.monotonic() - started_total, 3),
                "galleryHidden": False,
            }
            history_path = self._persist_vector_history(record)
            persisted = True
            if creative_result:
                raw_history = str(creative_result.get("HistoryPath") or "")
                if raw_history:
                    self._hide_vector_raster_history(creative_result, prompt_id, preview_path)
            return {
                "assetType": "svg",
                "workflow": IMAGE_TO_SVG_VERSION,
                "provider": record["provider"],
                "promptId": prompt_id,
                "svgPath": str(svg_path),
                "previewPath": str(preview_path),
                "width": sanitized.width,
                "height": sanitized.height,
                "pathCount": sanitized.path_count,
                "nodeCount": sanitized.node_count,
                "sanitized": True,
                "sourceKind": source_kind,
                "mode": clean["mode"],
                "stylization": clean["stylization"],
                "detail": clean["detail"],
                "colors": clean["colors"],
                "background": clean["background"],
                "cropMode": clean["cropMode"],
                "historyPath": str(history_path),
            }
        finally:
            if source_owned:
                source_path.unlink(missing_ok=True)
            if creative_result and not persisted:
                # The Krea child is deliberately left visible on downstream
                # failure, matching the accepted Vector failure-evidence rule.
                pass
            if prepared_path:
                prepared_path.unlink(missing_ok=True)
            if raw_svg_path:
                raw_svg_path.unlink(missing_ok=True)
            if not persisted:
                if svg_path:
                    svg_path.unlink(missing_ok=True)
                if preview_path:
                    preview_path.unlink(missing_ok=True)


class ImageToSvgApiMixin:
    @staticmethod
    def _validate_source_request(source: Any) -> dict[str, Any]:
        return validate_image_to_svg_request({"source": source})["source"]

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        if method.upper() == "POST" and path == "/api/vector/image-to-svg":
            try:
                request = validate_image_to_svg_request(self._decode_json(body))
                if not getattr(self.bridge, "_vector_dependency_ready", lambda: False)():
                    return 409, {"error": "Vector dependency is not ready. Install the pinned Vectorizer first."}
                if request["mode"] == "photo-stylized" and request["stylization"] == "creative":
                    ready = getattr(self.bridge, "_krea_image_edit_ready", lambda: False)()
                    if not ready:
                        return 409, {"error": "Photo Stylized / Creative is unavailable because Krea Image Edit is not ready."}
                submit = getattr(self, "_submit_vector_job", None)
                if not callable(submit):
                    raise base.StableAmdBridgeError("Image-to-SVG async transport is unavailable.")
                return 202, submit(request, "image_to_svg")
            except ValueError as exc:
                return 400, {"error": str(exc)}
            except base.StableAmdBridgeError as exc:
                return 409, {"error": str(exc)}
        return super().dispatch(method, target, body)


def image_to_svg_capabilities(bridge: Any) -> dict[str, Any]:
    creative_ready = bool(getattr(bridge, "_krea_image_edit_ready", lambda: False)())
    return {
        "workflow": IMAGE_TO_SVG_VERSION,
        "sourceKinds": sorted(IMAGE_TO_SVG_SOURCE_KINDS),
        "modes": ["artwork", "photo-direct", "photo-stylized"],
        "stylizations": ["preserve", "creative"],
        "creative": {
            "provider": "krea2-ostris-edit",
            "ready": creative_ready,
        },
        "details": sorted(IMAGE_TO_SVG_DETAILS),
        "colors": ["auto", 2, 4, 8, 16],
        "backgrounds": sorted(IMAGE_TO_SVG_BACKGROUNDS),
        "cropModes": sorted(IMAGE_TO_SVG_CROPS),
        "advanced": {
            "smoothing": [0, 100],
            "edgeStrength": [0, 100],
            "denoise": [0, 100],
            "posterize": [0, 100],
            "backgroundTolerance": [0, 255],
        },
    }
