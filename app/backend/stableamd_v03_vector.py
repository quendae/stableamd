from __future__ import annotations

import re
import statistics
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Sequence

import stableamd_server as base

VECTOR_PROMPT_VERSION = "text-to-svg-v1"
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
