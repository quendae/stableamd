from __future__ import annotations

import uuid
from pathlib import Path

import stableamd_server as base

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def render_svg_preview(svg_text: str, output_path: Path) -> Path:
    if not isinstance(svg_text, str) or not svg_text.strip():
        raise base.StableAmdBridgeError("SVG preview requires a non-empty sanitized SVG document.")

    try:
        import resvg_py
    except ImportError as exc:
        raise base.StableAmdBridgeError(
            "SVG preview renderer is not installed. Install the Vector dependency."
        ) from exc

    try:
        payload = resvg_py.svg_to_bytes(svg_string=svg_text)
    except Exception as exc:
        raise base.StableAmdBridgeError(f"SVG preview rendering failed: {exc}") from exc

    if not isinstance(payload, (bytes, bytearray)) or not bytes(payload).startswith(PNG_SIGNATURE):
        raise base.StableAmdBridgeError("SVG preview renderer did not return a valid PNG image.")

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_bytes(bytes(payload))
        temporary.replace(destination)
    except OSError as exc:
        raise base.StableAmdBridgeError(f"SVG preview PNG could not be persisted: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination
