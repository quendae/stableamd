from __future__ import annotations

import json
import re
import statistics
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import stableamd_server as base
import stableamd_v03_svg_preview as svg_preview
import stableamd_v03_svg_sanitize as svg_sanitize
import stableamd_v03_svg_vectorizer as vectorizer

VECTOR_PROMPT_VERSION = "text-to-svg-v1"
VECTOR_PROVIDER = "zimage-vtrace"
VECTOR_WIDTH = 1024
VECTOR_HEIGHT = 1024
VECTOR_STYLES = {"icon", "illustration"}
VECTOR_DETAILS = {"simple", "medium", "detailed"}
VECTOR_COLOR_LIMITS = {2, 4, 8, 16}
VECTOR_BACKGROUNDS = {"transparent", "solid"}
VECTOR_MAX_PROMPT_CHARS = 2000
VECTOR_MAX_SEED = (1 << 63) - 1
_VECTOR_REQUEST_FIELDS = {
    "prompt",
    "style",
    "detail",
    "colors",
    "background",
    "backgroundColor",
    "seed",
}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _value(record: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return default


def validate_text_to_svg_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Text-to-SVG request must be a JSON object.")
    unsupported = sorted(set(payload) - _VECTOR_REQUEST_FIELDS)
    if unsupported:
        raise ValueError("Unsupported Text-to-SVG field(s): " + ", ".join(unsupported))

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Text-to-SVG prompt must be a non-empty string.")
    prompt = prompt.strip()
    if len(prompt) > VECTOR_MAX_PROMPT_CHARS:
        raise ValueError(f"Text-to-SVG prompt must be {VECTOR_MAX_PROMPT_CHARS} characters or fewer.")

    style = payload.get("style", "icon")
    if not isinstance(style, str) or style.strip().lower() not in VECTOR_STYLES:
        raise ValueError("Text-to-SVG style must be icon or illustration.")
    style = style.strip().lower()

    detail = payload.get("detail", "medium")
    if not isinstance(detail, str) or detail.strip().lower() not in VECTOR_DETAILS:
        raise ValueError("Text-to-SVG detail must be simple, medium, or detailed.")
    detail = detail.strip().lower()

    colors = payload.get("colors", "auto")
    if isinstance(colors, str):
        if colors.strip().lower() != "auto":
            raise ValueError("Text-to-SVG colors must be auto, 2, 4, 8, or 16.")
        colors = "auto"
    elif isinstance(colors, bool) or not isinstance(colors, int) or colors not in VECTOR_COLOR_LIMITS:
        raise ValueError("Text-to-SVG colors must be auto, 2, 4, 8, or 16.")

    background = payload.get("background", "transparent")
    if not isinstance(background, str) or background.strip().lower() not in VECTOR_BACKGROUNDS:
        raise ValueError("Text-to-SVG background must be transparent or solid.")
    background = background.strip().lower()

    clean: dict[str, Any] = {
        "prompt": prompt,
        "style": style,
        "detail": detail,
        "colors": colors,
        "background": background,
    }

    if "seed" in payload:
        seed = payload.get("seed")
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or seed < 0
            or seed > VECTOR_MAX_SEED
        ):
            raise ValueError(f"Text-to-SVG seed must be an integer between 0 and {VECTOR_MAX_SEED}.")
        clean["seed"] = seed

    supplied_background_color = payload.get("backgroundColor")
    if background == "transparent":
        if supplied_background_color is not None:
            raise ValueError("backgroundColor is valid only when Text-to-SVG background is solid.")
    else:
        background_color = "#ffffff" if supplied_background_color is None else supplied_background_color
        if not isinstance(background_color, str) or not _HEX_COLOR_RE.fullmatch(background_color.strip()):
            raise ValueError("Text-to-SVG backgroundColor must be a #RRGGBB color.")
        clean["backgroundColor"] = background_color.strip().lower()

    return clean


def build_vector_prompt(request: dict[str, Any]) -> str:
    clean = validate_text_to_svg_request(request)
    user_prompt = clean["prompt"]
    style = clean["style"]
    detail = clean["detail"]
    colors = clean["colors"]
    background = clean["background"]

    if style == "icon":
        style_instruction = (
            "Create a flat vector icon with one dominant centered symbol, a simple silhouette, "
            "clear negative space, and immediately readable shape language."
        )
    else:
        style_instruction = (
            "Create a flat vector illustration; multiple objects are allowed in a coherent full composition, "
            "with clear layered silhouettes and uncluttered spacing."
        )

    detail_instruction = {
        "simple": "Keep the geometry simple with a small number of broad shapes and minimal internal detail.",
        "medium": "Use balanced vector detail with clean separations and avoid tiny decorative fragments.",
        "detailed": "Use richer vector detail while keeping every feature as clean intentional geometry suitable for tracing.",
    }[detail]

    if colors == "auto":
        palette_instruction = "Use a restrained coherent color palette suitable for vector tracing."
    else:
        palette_instruction = f"Use a maximum palette of {colors} colors."

    if background == "transparent":
        background_instruction = (
            "Render on a pure white, flat, uniform background that reaches every canvas edge; "
            "do not use white as an exterior halo or drop shadow."
        )
    else:
        background_instruction = (
            f"Use {clean['backgroundColor']} as a flat full-canvas background with no texture or lighting gradient."
        )

    return " ".join(
        [
            user_prompt,
            style_instruction,
            detail_instruction,
            "Use solid shapes, crisp edges, no gradients, no text, no letters, no numbers, no watermark.",
            "Avoid photorealism, soft shadows, blur, noise, texture, reflections, and raster-like detail.",
            palette_instruction,
            background_instruction,
        ]
    )


def _pixel_rgb(pixel: Sequence[int]) -> tuple[int, int, int]:
    if len(pixel) < 3:
        raise ValueError("Vector raster pixels must contain RGB channels.")
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _border_connected_background_mask(
    pixels: Sequence[Sequence[int]],
    width: int,
    height: int,
    *,
    tolerance: int = 18,
) -> set[int]:
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        raise ValueError("Vector raster dimensions do not match its pixel buffer.")
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0 or tolerance > 255:
        raise ValueError("Vector background tolerance must be an integer between 0 and 255.")

    corner_indices = (0, width - 1, (height - 1) * width, height * width - 1)
    corners = [_pixel_rgb(pixels[index]) for index in corner_indices]
    reference = tuple(int(round(statistics.median(channel))) for channel in zip(*corners))

    def matches(index: int) -> bool:
        red, green, blue = _pixel_rgb(pixels[index])
        return (
            abs(red - reference[0]) <= tolerance
            and abs(green - reference[1]) <= tolerance
            and abs(blue - reference[2]) <= tolerance
        )

    border_indices: list[int] = []
    for x in range(width):
        border_indices.append(x)
        if height > 1:
            border_indices.append((height - 1) * width + x)
    for y in range(1, max(1, height - 1)):
        border_indices.append(y * width)
        if width > 1:
            border_indices.append(y * width + width - 1)

    visited: set[int] = set()
    queue: deque[int] = deque()
    for index in border_indices:
        if index not in visited and matches(index):
            visited.add(index)
            queue.append(index)

    while queue:
        index = queue.popleft()
        x = index % width
        y = index // width
        neighbours: list[int] = []
        if x > 0:
            neighbours.append(index - 1)
        if x + 1 < width:
            neighbours.append(index + 1)
        if y > 0:
            neighbours.append(index - width)
        if y + 1 < height:
            neighbours.append(index + width)
        for neighbour in neighbours:
            if neighbour in visited or not matches(neighbour):
                continue
            visited.add(neighbour)
            queue.append(neighbour)
    return visited


def prepare_vector_raster(
    source_path: Path,
    destination_path: Path,
    background: str,
    tolerance: int = 18,
) -> Path:
    normalized_background = str(background or "").strip().lower()
    if normalized_background not in VECTOR_BACKGROUNDS:
        raise base.StableAmdBridgeError("Vector background must be transparent or solid.")
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0 or tolerance > 255:
        raise base.StableAmdBridgeError("Vector background tolerance must be an integer between 0 and 255.")

    try:
        from PIL import Image
    except ImportError as exc:
        raise base.StableAmdBridgeError("Vector raster preparation requires Pillow in the managed StableAMD runtime.") from exc

    source = Path(source_path).resolve()
    if not source.is_file():
        raise base.StableAmdBridgeError(f"Vector raster source was not found: '{source}'.")
    destination = Path(destination_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}")

    try:
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
        if normalized_background == "transparent":
            rgba_pixels = list(image.getdata())
            rgb_pixels = [(pixel[0], pixel[1], pixel[2]) for pixel in rgba_pixels]
            mask = _border_connected_background_mask(
                rgb_pixels,
                image.width,
                image.height,
                tolerance=tolerance,
            )
            if mask:
                updated = list(rgba_pixels)
                for index in mask:
                    red, green, blue, _alpha = updated[index]
                    updated[index] = (red, green, blue, 0)
                image.putdata(updated)
        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(destination)
    except base.StableAmdBridgeError:
        raise
    except Exception as exc:
        raise base.StableAmdBridgeError(f"Vector raster preparation failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)

    return destination


class VectorBridgeMixin:
    """Text-to-SVG product orchestration layered on the accepted Z-Image provider."""

    def vector_dependency(self) -> dict[str, Any]:
        return vectorizer.vector_dependency_status(self.repo_root)

    def install_vector_dependency(self, dependency_id: str = vectorizer.VECTOR_DEPENDENCY_ID) -> dict[str, Any]:
        if str(dependency_id or "").strip() != vectorizer.VECTOR_DEPENDENCY_ID:
            raise base.StableAmdBridgeError(
                f"Unknown Vector dependency '{dependency_id}'. Expected {vectorizer.VECTOR_DEPENDENCY_ID}."
            )
        return vectorizer.install_vector_dependencies(self.repo_root)

    def _vector_dependency_ready(self) -> bool:
        return bool(self.vector_dependency().get("ready"))

    def _select_vector_model(self) -> dict[str, Any]:
        models = [item for item in self.models() if isinstance(item, dict)]
        support = self.model_support()
        support_models = support.get("models", []) if isinstance(support, dict) else []
        support_by_id = {
            str(item.get("id") or ""): item
            for item in support_models
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        for model in models:
            family = str(_value(model, "family", "Family", default="")).strip().lower()
            if family != "z-image-turbo":
                continue
            model_id = str(_value(model, "id", "Id", default="")).strip()
            support_entry = support_by_id.get(model_id)
            capabilities = support_entry.get("capabilities") if isinstance(support_entry, dict) else None
            if isinstance(capabilities, dict) and str(capabilities.get("txt2img") or "").lower() == "supported":
                return model
        raise base.StableAmdBridgeError(
            "Text-to-SVG requires an installed Z-Image Turbo model with supported txt2img capability."
        )

    def _build_vector_prompt(self, request: dict[str, Any]) -> str:
        return build_vector_prompt(request)

    def _generate_vector_raster(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        prompt: str,
    ) -> dict[str, Any]:
        model_id = str(_value(model, "id", "Id", default="")).strip()
        if not model_id:
            raise base.StableAmdBridgeError("Selected Z-Image Turbo model has no product model id.")
        raster_request: dict[str, Any] = {
            "mode": "txt2img",
            "modelId": model_id,
            "prompt": prompt,
            "width": VECTOR_WIDTH,
            "height": VECTOR_HEIGHT,
        }
        if "seed" in request:
            raster_request["seed"] = int(request["seed"])
        result = super().generate(raster_request)
        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Z-Image Turbo did not return a generation result for Text-to-SVG.")
        return result

    def _release_vector_runtime(self) -> bool:
        post = getattr(self, "_post_comfy_no_content", None)
        if not callable(post):
            return False
        try:
            post(
                "free",
                {"unload_models": True, "free_memory": True},
                timeout=10,
            )
        except (OSError, base.StableAmdBridgeError):
            return False
        return True

    def _prepare_vector_raster_file(
        self,
        source_path: Path,
        destination_path: Path,
        background: str,
    ) -> Path:
        return prepare_vector_raster(source_path, destination_path, background)

    def _run_vectorizer(
        self,
        prepared_path: Path,
        raw_svg_path: Path,
        request: dict[str, Any],
    ) -> Path:
        colors = request.get("colors", "auto")
        max_colors = None if colors == "auto" else int(colors)
        return vectorizer.run_vtracer(
            self.repo_root,
            prepared_path,
            raw_svg_path,
            detail=str(request["detail"]),
            max_colors=max_colors,
        )

    def _sanitize_vector_svg(self, raw_svg_path: Path) -> svg_sanitize.SanitizedSvg:
        path = Path(raw_svg_path).resolve()
        try:
            if path.stat().st_size > 2_000_000:
                raise base.StableAmdBridgeError("VTracer SVG exceeds the 2 MB Clean SVG limit.")
            source = path.read_text(encoding="utf-8")
        except base.StableAmdBridgeError:
            raise
        except (OSError, UnicodeDecodeError) as exc:
            raise base.StableAmdBridgeError(f"VTracer SVG could not be read: {exc}") from exc
        return svg_sanitize.sanitize_svg(source)

    def _render_vector_preview(self, svg_text: str, preview_path: Path) -> Path:
        return svg_preview.render_svg_preview(svg_text, preview_path)

    def _persist_vector_history(self, record: dict[str, Any]) -> Path:
        saver = getattr(self, "_save_bundle_history", None)
        if not callable(saver):
            raise base.StableAmdBridgeError("Text-to-SVG cannot persist Gallery history.")
        return Path(saver(record)).resolve()

    def _hide_vector_raster_history(
        self,
        raster_result: dict[str, Any],
        vector_prompt_id: str,
        preview_path: Path,
    ) -> bool:
        raw_history = str(_value(raster_result, "HistoryPath", "historyPath", default="") or "").strip()
        if not raw_history:
            return False
        history_root = (Path(self.repo_root).resolve() / ".runtime" / "stableamd" / "history").resolve()
        history_path = Path(raw_history).resolve()
        if history_root not in history_path.parents or not history_path.is_file():
            return False
        try:
            record = json.loads(history_path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return False
            record["galleryHidden"] = True
            record["vectorParentPromptId"] = str(vector_prompt_id)
            record["vectorPreviewPath"] = str(Path(preview_path).resolve())
            temporary = history_path.with_suffix(history_path.suffix + f".tmp-{uuid.uuid4().hex}")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(history_path)
            return True
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False

    @staticmethod
    def _seconds(value: Any) -> float:
        try:
            return max(0.0, float(value or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def text_to_svg(self, request: dict[str, Any]) -> dict[str, Any]:
        clean = validate_text_to_svg_request(request)
        if not self._vector_dependency_ready():
            raise base.StableAmdBridgeError(
                "Vector dependency is not ready. Install the pinned Text-to-SVG Vector dependency first."
            )

        model = self._select_vector_model()
        effective_prompt = self._build_vector_prompt(clean)
        started_total = time.monotonic()
        raster_result = self._generate_vector_raster(clean, model, effective_prompt)
        raster_image = base.resolve_output_image(
            self.repo_root,
            str(_value(raster_result, "ImagePath", "imagePath", default="") or ""),
        )

        # Explicitly release the model working set before CPU-side tracing. This
        # is intentionally Vector-scoped so ordinary Z-Image caching is unchanged.
        self._release_vector_runtime()

        vector_root = (
            Path(self.repo_root).resolve() / ".runtime" / "stableamd" / "output" / "vector"
        ).resolve()
        vector_root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        prompt_id = f"vector-{token}"
        prepared_path = vector_root / f"{prompt_id}.prepared.png"
        raw_svg_path = vector_root / f"{prompt_id}.raw.svg"
        svg_path = vector_root / f"{prompt_id}.svg"
        preview_path = vector_root / f"{prompt_id}-preview.png"
        sanitized_temp = svg_path.with_suffix(svg_path.suffix + f".tmp-{uuid.uuid4().hex}")
        persisted = False
        vector_started = time.monotonic()

        try:
            self._prepare_vector_raster_file(raster_image, prepared_path, str(clean["background"]))
            self._run_vectorizer(prepared_path, raw_svg_path, clean)
            sanitized = self._sanitize_vector_svg(raw_svg_path)
            sanitized_temp.write_text(sanitized.xml, encoding="utf-8")
            sanitized_temp.replace(svg_path)
            self._render_vector_preview(sanitized.xml, preview_path)

            vector_seconds = round(time.monotonic() - vector_started, 3)
            generation_seconds = self._seconds(
                _value(raster_result, "GenerationSeconds", "generationSeconds", default=0.0)
            )
            seed = _value(raster_result, "Seed", "seed", default=clean.get("seed"))
            model_id = str(_value(raster_result, "ModelId", "modelId", default=_value(model, "id", "Id", default="")) or "")
            model_name = str(_value(raster_result, "ModelName", "modelName", default=_value(model, "name", "Name", default="Z-Image Turbo")) or "Z-Image Turbo")
            raster_history = str(_value(raster_result, "HistoryPath", "historyPath", default="") or "")
            raster_prompt_id = str(_value(raster_result, "PromptId", "promptId", default="") or "")
            created_at = datetime.now(timezone.utc).isoformat()
            record = {
                "schemaVersion": 3,
                "createdAtUtc": created_at,
                "promptId": prompt_id,
                "mode": "vector",
                "assetType": "svg",
                "provider": VECTOR_PROVIDER,
                "prompt": clean["prompt"],
                "effectiveVectorPrompt": effective_prompt,
                "vectorPromptVersion": VECTOR_PROMPT_VERSION,
                "style": clean["style"],
                "detail": clean["detail"],
                "colors": clean["colors"],
                "background": clean["background"],
                "backgroundColor": clean.get("backgroundColor"),
                "seed": seed,
                "modelId": model_id,
                "modelName": model_name,
                "vectorizerVersion": vectorizer.VTRACER_VERSION,
                "sanitizerVersion": svg_sanitize.SANITIZER_VERSION,
                "svgPath": str(svg_path),
                "previewPath": str(preview_path),
                "imagePath": str(preview_path),
                "width": sanitized.width,
                "height": sanitized.height,
                "pathCount": sanitized.path_count,
                "nodeCount": sanitized.node_count,
                "sanitized": True,
                "childRasterPromptId": raster_prompt_id,
                "childRasterHistoryPath": raster_history,
                "childRasterImagePath": str(raster_image),
                "ownedIntermediatePaths": [str(raster_image)],
                "generationSeconds": round(generation_seconds, 3),
                "vectorizationSeconds": vector_seconds,
                "totalSeconds": round(time.monotonic() - started_total, 3),
                "galleryHidden": False,
            }
            history_path = self._persist_vector_history(record)
            persisted = True
            self._hide_vector_raster_history(raster_result, prompt_id, preview_path)
            return {
                "assetType": "svg",
                "provider": VECTOR_PROVIDER,
                "svgPath": str(svg_path),
                "previewPath": str(preview_path),
                "width": sanitized.width,
                "height": sanitized.height,
                "pathCount": sanitized.path_count,
                "nodeCount": sanitized.node_count,
                "sanitized": True,
                "seed": seed,
                "historyPath": str(history_path),
            }
        finally:
            prepared_path.unlink(missing_ok=True)
            raw_svg_path.unlink(missing_ok=True)
            sanitized_temp.unlink(missing_ok=True)
            if not persisted:
                svg_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)


class VectorApiMixin:
    """Dedicated product API for Vector; it never reuses generation validation."""

    @staticmethod
    def _validate_vector_install_request(request: Any) -> str:
        if not isinstance(request, dict):
            raise ValueError("Vector install request must be a JSON object.")
        unsupported = sorted(set(request) - {"id"})
        if unsupported:
            raise ValueError("Unsupported Vector install field(s): " + ", ".join(unsupported))
        dependency_id = request.get("id", vectorizer.VECTOR_DEPENDENCY_ID)
        if not isinstance(dependency_id, str) or dependency_id.strip() != vectorizer.VECTOR_DEPENDENCY_ID:
            raise ValueError(
                f"Vector dependency id must be {vectorizer.VECTOR_DEPENDENCY_ID}."
            )
        return vectorizer.VECTOR_DEPENDENCY_ID

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        method = (method or "").upper()
        path = target.split("?", 1)[0]
        try:
            if method == "GET" and path == "/api/vector/dependency":
                return 200, self.bridge.vector_dependency()
            if method == "POST" and path == "/api/vector/install":
                dependency_id = self._validate_vector_install_request(self._decode_json(body))
                return 200, self.bridge.install_vector_dependency(dependency_id)
            if method == "POST" and path == "/api/vector/text-to-svg":
                request = validate_text_to_svg_request(self._decode_json(body))
                return 202, self._submit_bridge_job(
                    request,
                    "text_to_svg",
                    job_kind="vector",
                )
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except base.StableAmdBridgeError as exc:
            return 409, {"error": str(exc)}
        return super().dispatch(method, target, body)
