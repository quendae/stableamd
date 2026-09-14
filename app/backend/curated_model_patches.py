from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


CATALOG_NAME = "model-patches.v0.3.json"
ALLOWED_SOURCE_HOSTS = {"huggingface.co"}
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_MODEL_PATCH_BYTES = 8 * 1024 * 1024 * 1024


class CuratedModelPatchError(RuntimeError):
    pass


def _catalog_path(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / "config" / CATALOG_NAME


def load_curated_model_patches(repo_root: Path) -> list[dict[str, Any]]:
    path = _catalog_path(repo_root)
    if not path.is_file():
        raise CuratedModelPatchError(f"Curated model patch catalog is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CuratedModelPatchError(f"Curated model patch catalog is invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise CuratedModelPatchError("Curated model patch catalog has an unsupported schema.")
    models = payload.get("models")
    if not isinstance(models, list):
        raise CuratedModelPatchError("Curated model patch catalog must contain a models array.")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(models):
        if not isinstance(item, dict):
            raise CuratedModelPatchError(f"Curated model patch entry {index + 1} must be an object.")
        model_id = str(item.get("id") or "").strip()
        filename = str(item.get("filename") or "").strip()
        source_url = str(item.get("sourceUrl") or "").strip()
        sha256 = str(item.get("sha256") or "").strip().lower()
        name = str(item.get("name") or model_id).strip()
        family = str(item.get("family") or "").strip().lower()
        if not model_id or model_id in seen:
            raise CuratedModelPatchError("Curated model patch ids must be non-empty and unique.")
        if not filename or Path(filename).name != filename:
            raise CuratedModelPatchError(f"Curated model patch '{model_id}' has an unsafe filename.")
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_SOURCE_HOSTS:
            raise CuratedModelPatchError(f"Curated model patch '{model_id}' has an untrusted source URL.")
        if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
            raise CuratedModelPatchError(f"Curated model patch '{model_id}' has an invalid SHA-256 checksum.")
        size = item.get("sizeBytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > MAX_MODEL_PATCH_BYTES:
            raise CuratedModelPatchError(f"Curated model patch '{model_id}' has an invalid expected size.")
        if not family:
            raise CuratedModelPatchError(f"Curated model patch '{model_id}' must declare a model family.")
        seen.add(model_id)
        normalized.append(
            {
                "id": model_id,
                "name": name,
                "family": family,
                "filename": filename,
                "purpose": str(item.get("purpose") or "").strip(),
                "sourceUrl": source_url,
                "sha256": sha256,
                "sizeBytes": int(size),
                "license": str(item.get("license") or "Unknown").strip(),
                "homepage": str(item.get("homepage") or "").strip(),
            }
        )
    return normalized


def public_catalog(repo_root: Path, registered_patches: list[str] | None = None) -> list[dict[str, Any]]:
    root = Path(repo_root).resolve() / ".runtime" / "stableamd" / "models" / "model_patches"
    registered = {str(value).replace("\\", "/").lower() for value in (registered_patches or [])}
    result: list[dict[str, Any]] = []
    for item in load_curated_model_patches(repo_root):
        destination = (root / item["filename"]).resolve()
        on_disk = destination.is_file()
        actual_bytes = destination.stat().st_size if on_disk else None
        size_valid = bool(on_disk and actual_bytes == item["sizeBytes"])
        exposed = item["filename"].replace("\\", "/").lower() in registered
        ready = bool(size_valid and exposed)
        result.append(
            {
                "id": item["id"],
                "name": item["name"],
                "family": item["family"],
                "filename": item["filename"],
                "purpose": item["purpose"],
                "sizeBytes": item["sizeBytes"],
                "actualBytes": actual_bytes,
                "expectedSha256": item["sha256"],
                "license": item["license"],
                "homepage": item["homepage"],
                "installedOnDisk": on_disk,
                "integrity": "missing" if not on_disk else ("size-ok" if size_valid else "size-mismatch"),
                "ready": ready,
                "restartRequired": bool(size_valid and not exposed),
            }
        )
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


def install_curated_model_patch(
    repo_root: Path,
    model_id: str,
    *,
    registered_patches: list[str] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    requested = str(model_id or "").strip()
    item = next((entry for entry in load_curated_model_patches(repo_root) if entry["id"] == requested), None)
    if item is None:
        raise CuratedModelPatchError(f"Unknown curated model patch id '{requested}'.")

    root = (repo_root / ".runtime" / "stableamd" / "models" / "model_patches").resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / item["filename"]).resolve()
    if destination.parent != root:
        raise CuratedModelPatchError("Curated model patch destination escaped the managed model_patches folder.")

    already_installed = False
    if destination.is_file():
        if destination.stat().st_size != item["sizeBytes"] or _sha256_file(destination) != item["sha256"]:
            raise CuratedModelPatchError(
                f"A different or corrupt file already exists at '{destination.name}'. Remove or rename it before installing the curated model patch."
            )
        already_installed = True
    else:
        temporary = root / f".{destination.name}.partial-{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        total = 0
        request = Request(
            item["sourceUrl"],
            headers={"User-Agent": "StableAMD/0.3 curated-model-patch-installer"},
            method="GET",
        )
        try:
            with opener(request, timeout=60) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > item["sizeBytes"] or total > MAX_MODEL_PATCH_BYTES:
                        raise CuratedModelPatchError("Curated model patch download exceeded its pinned expected size.")
                    digest.update(chunk)
                    output.write(chunk)
            if total != item["sizeBytes"]:
                raise CuratedModelPatchError(
                    f"Curated model patch download size mismatch: expected {item['sizeBytes']} bytes, received {total}."
                )
            actual_hash = digest.hexdigest()
            if actual_hash != item["sha256"]:
                raise CuratedModelPatchError(
                    f"Curated model patch checksum mismatch for '{item['name']}'. The downloaded file was not installed."
                )
            temporary.replace(destination)
        except CuratedModelPatchError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise CuratedModelPatchError(f"Could not download curated model patch '{item['name']}': {exc}") from exc

    registered = {str(value).replace("\\", "/").lower() for value in (registered_patches or [])}
    ready = item["filename"].replace("\\", "/").lower() in registered
    return {
        "id": item["id"],
        "name": item["name"],
        "family": item["family"],
        "filename": item["filename"],
        "license": item["license"],
        "path": str(destination),
        "alreadyInstalled": already_installed,
        "installed": True,
        "ready": ready,
        "restartRequired": not ready,
        "sha256": item["sha256"],
        "sizeBytes": item["sizeBytes"],
    }
