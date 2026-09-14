from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


CATALOG_NAME = "upscalers.v0.3.json"
ALLOWED_SOURCE_HOSTS = {"github.com", "huggingface.co"}
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPSCALER_BYTES = 512 * 1024 * 1024


class CuratedUpscalerError(RuntimeError):
    pass


def _catalog_path(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / "config" / CATALOG_NAME


def load_curated_upscalers(repo_root: Path) -> list[dict[str, Any]]:
    path = _catalog_path(repo_root)
    if not path.is_file():
        raise CuratedUpscalerError(f"Curated upscaler catalog is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CuratedUpscalerError(f"Curated upscaler catalog is invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise CuratedUpscalerError("Curated upscaler catalog has an unsupported schema.")
    models = payload.get("models")
    if not isinstance(models, list):
        raise CuratedUpscalerError("Curated upscaler catalog must contain a models array.")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(models):
        if not isinstance(item, dict):
            raise CuratedUpscalerError(f"Curated upscaler entry {index + 1} must be an object.")
        model_id = str(item.get("id") or "").strip()
        filename = str(item.get("filename") or "").strip()
        source_url = str(item.get("sourceUrl") or "").strip()
        sha256 = str(item.get("sha256") or "").strip().lower()
        name = str(item.get("name") or model_id).strip()
        if not model_id or model_id in seen:
            raise CuratedUpscalerError("Curated upscaler ids must be non-empty and unique.")
        if not filename or Path(filename).name != filename:
            raise CuratedUpscalerError(f"Curated upscaler '{model_id}' has an unsafe filename.")
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_SOURCE_HOSTS:
            raise CuratedUpscalerError(f"Curated upscaler '{model_id}' has an untrusted source URL.")
        if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
            raise CuratedUpscalerError(f"Curated upscaler '{model_id}' has an invalid SHA-256 checksum.")
        size = item.get("sizeBytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > MAX_UPSCALER_BYTES:
            raise CuratedUpscalerError(f"Curated upscaler '{model_id}' has an invalid expected size.")
        scale = item.get("nativeScale")
        if scale not in {2, 4, 8}:
            raise CuratedUpscalerError(f"Curated upscaler '{model_id}' has an invalid native scale.")
        seen.add(model_id)
        normalized.append({
            "id": model_id,
            "name": name,
            "filename": filename,
            "nativeScale": int(scale),
            "purpose": str(item.get("purpose") or "").strip(),
            "sourceUrl": source_url,
            "sha256": sha256,
            "sizeBytes": int(size),
            "license": str(item.get("license") or "Unknown").strip(),
            "homepage": str(item.get("homepage") or "").strip(),
            "nonCommercial": item.get("nonCommercial") is True,
        })
    return normalized


def public_catalog(repo_root: Path, registered_models: list[str] | None = None) -> list[dict[str, Any]]:
    root = Path(repo_root).resolve() / ".runtime" / "stableamd" / "models" / "upscale_models"
    registered = {str(value).replace("\\", "/").lower() for value in (registered_models or [])}
    result: list[dict[str, Any]] = []
    for item in load_curated_upscalers(repo_root):
        destination = (root / item["filename"]).resolve()
        on_disk = destination.is_file()
        ready = item["filename"].replace("\\", "/").lower() in registered
        result.append({
            "id": item["id"],
            "name": item["name"],
            "filename": item["filename"],
            "nativeScale": item["nativeScale"],
            "purpose": item["purpose"],
            "sizeBytes": item["sizeBytes"],
            "license": item["license"],
            "homepage": item["homepage"],
            "nonCommercial": item["nonCommercial"],
            "installedOnDisk": on_disk,
            "ready": ready,
            "restartRequired": on_disk and not ready,
        })
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def install_curated_upscaler(
    repo_root: Path,
    model_id: str,
    *,
    registered_models: list[str] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    requested = str(model_id or "").strip()
    item = next((entry for entry in load_curated_upscalers(repo_root) if entry["id"] == requested), None)
    if item is None:
        raise CuratedUpscalerError(f"Unknown curated upscaler id '{requested}'.")

    root = (repo_root / ".runtime" / "stableamd" / "models" / "upscale_models").resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / item["filename"]).resolve()
    if destination.parent != root:
        raise CuratedUpscalerError("Curated upscaler destination escaped the managed model folder.")

    already_installed = False
    if destination.is_file():
        if destination.stat().st_size != item["sizeBytes"] or _sha256_file(destination) != item["sha256"]:
            raise CuratedUpscalerError(
                f"A different file already exists at '{destination.name}'. Remove or rename it before installing the curated model."
            )
        already_installed = True
    else:
        temporary = root / f".{destination.name}.partial-{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        total = 0
        request = Request(
            item["sourceUrl"],
            headers={"User-Agent": "StableAMD/0.3 curated-upscaler-installer"},
            method="GET",
        )
        try:
            with opener(request, timeout=60) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > item["sizeBytes"] or total > MAX_UPSCALER_BYTES:
                        raise CuratedUpscalerError("Curated upscaler download exceeded its pinned expected size.")
                    digest.update(chunk)
                    output.write(chunk)
            if total != item["sizeBytes"]:
                raise CuratedUpscalerError(
                    f"Curated upscaler download size mismatch: expected {item['sizeBytes']} bytes, received {total}."
                )
            actual_hash = digest.hexdigest()
            if actual_hash != item["sha256"]:
                raise CuratedUpscalerError(
                    f"Curated upscaler checksum mismatch for '{item['name']}'. The downloaded file was not installed."
                )
            temporary.replace(destination)
        except CuratedUpscalerError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise CuratedUpscalerError(f"Could not download curated upscaler '{item['name']}': {exc}") from exc

    registered = {str(value).replace("\\", "/").lower() for value in (registered_models or [])}
    ready = item["filename"].replace("\\", "/").lower() in registered
    return {
        "id": item["id"],
        "name": item["name"],
        "filename": item["filename"],
        "nativeScale": item["nativeScale"],
        "license": item["license"],
        "nonCommercial": item["nonCommercial"],
        "path": str(destination),
        "alreadyInstalled": already_installed,
        "installed": True,
        "ready": ready,
        "restartRequired": not ready,
        "sha256": item["sha256"],
        "sizeBytes": item["sizeBytes"],
    }
