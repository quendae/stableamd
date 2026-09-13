from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any, Iterable

MAX_SAFETENSORS_HEADER_BYTES = 16 * 1024 * 1024
KNOWN_FAMILIES = ("shared", "sd15", "sdxl", "sd3", "z-image", "flux", "krea")

_METADATA_KEYS = (
    "ss_base_model_version",
    "ss_sd_model_name",
    "ss_base_model_name",
    "modelspec.architecture",
    "modelspec.title",
    "modelspec.description",
)


def read_safetensors_metadata(path: Path) -> dict[str, str]:
    """Read only a safetensors JSON header and return string metadata.

    StableAMD never loads tensor payloads for compatibility discovery. Invalid,
    truncated or metadata-free files are treated as unknown instead of making
    model discovery fail.
    """

    try:
        with Path(path).open("rb") as stream:
            prefix = stream.read(8)
            if len(prefix) != 8:
                return {}
            (header_length,) = struct.unpack("<Q", prefix)
            if header_length <= 0 or header_length > MAX_SAFETENSORS_HEADER_BYTES:
                return {}
            encoded = stream.read(header_length)
            if len(encoded) != header_length:
                return {}
        header = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, struct.error, ValueError):
        return {}

    metadata = header.get("__metadata__") if isinstance(header, dict) else None
    if not isinstance(metadata, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in metadata.items():
        if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
            result[key] = str(value)
    return result


def normalize_model_family(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    raw = re.sub(r"\s+", "-", raw)
    if not raw:
        return "unknown"
    if raw in {"shared", "unknown"}:
        return raw
    if "z-image" in raw or "zimage" in raw:
        return "z-image"
    if "krea" in raw:
        return "krea"
    if "flux" in raw:
        return "flux"
    if raw.startswith("sdxl") or "sd-xl" in raw or "stable-diffusion-xl" in raw:
        return "sdxl"
    if raw.startswith("sd3") or "stable-diffusion-3" in raw:
        return "sd3"
    if raw in {"sd15", "sd1.5", "sd-1.5", "sd-v1-5"} or raw.startswith("sd1"):
        return "sd15"
    return raw


def _family_from_text(value: str) -> str | None:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return None

    # Order matters: SDXL/SD3 are more specific than generic SD1 markers.
    patterns = (
        ("z-image", (r"(?:^|[^a-z0-9])z-?image(?:[^a-z0-9]|$)", r"zimage")),
        ("krea", (r"(?:^|[^a-z0-9])krea(?:[^a-z0-9]|$)",)),
        ("flux", (r"(?:^|[^a-z0-9])flux(?:[^a-z0-9]|$)",)),
        ("sdxl", (r"sd-?xl", r"stable-?diffusion-?xl", r"sdxl-base", r"sdxl-base-v1")),
        ("sd3", (r"(?:^|[^a-z0-9])sd-?3(?:[^0-9]|$)", r"stable-?diffusion-?3")),
        ("sd15", (r"sd-?v?1-?5", r"sd-?1[._-]?5", r"stable-?diffusion-?1[._-]?5")),
    )
    for family, expressions in patterns:
        if any(re.search(expression, text) for expression in expressions):
            return family
    return None


def _metadata_family(metadata: dict[str, str]) -> tuple[str | None, str | None]:
    ordered_keys = [key for key in _METADATA_KEYS if key in metadata]
    ordered_keys.extend(key for key in metadata if key not in ordered_keys)
    for key in ordered_keys:
        family = _family_from_text(metadata.get(key, ""))
        if family:
            return family, key
    return None, None


def _folder_family(path: Path, root: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    for part in relative.parts[:-1]:
        normalized = part.lower().replace("_", "-")
        if normalized in KNOWN_FAMILIES:
            return normalized
    return None


def classify_lora(path: Path, root: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    root = Path(root).resolve()
    metadata = read_safetensors_metadata(path)

    family, metadata_key = _metadata_family(metadata)
    if family:
        confidence = "metadata"
        reason = f"safetensors metadata: {metadata_key}"
    else:
        family = _folder_family(path, root)
        if family:
            confidence = "folder"
            reason = f"family folder: {family}"
        else:
            family = _family_from_text(path.stem)
            if family:
                confidence = "filename"
                reason = "filename family hint"
            else:
                family = "unknown"
                confidence = "unknown"
                reason = "no reliable model-family metadata"

    try:
        name = path.relative_to(root).as_posix()
    except ValueError:
        name = path.name

    return {
        "name": name,
        "path": str(path),
        "family": family,
        "confidence": confidence,
        "reason": reason,
    }


def scan_lora_catalog(roots: Iterable[str | Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve()
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.safetensors"), key=lambda item: str(item).lower()):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved).lower()
            if key in seen_paths or not resolved.is_file():
                continue
            seen_paths.add(key)
            records.append(classify_lora(resolved, root))
    records.sort(key=lambda item: (str(item.get("name", "")).lower(), str(item.get("path", "")).lower()))
    return records


def families_compatible(model_family: str | None, lora_family: str | None) -> bool:
    model = normalize_model_family(model_family)
    lora = normalize_model_family(lora_family)
    if lora in {"unknown", "shared"} or model in {"unknown", "shared"}:
        return True
    return model == lora
