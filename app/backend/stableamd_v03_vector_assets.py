from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import stableamd_server as base
import stableamd_v03_svg_sanitize as svg_sanitize


def resolve_output_svg(repo_root: Path, requested_path: str) -> Path:
    """Resolve only SVG files inside StableAMD's managed Vector output root."""
    if not requested_path or not str(requested_path).strip():
        raise ValueError("Vector SVG path is required.")

    vector_root = (
        Path(repo_root).resolve() / ".runtime" / "stableamd" / "output" / "vector"
    ).resolve()
    candidate = Path(requested_path).expanduser().resolve()
    if candidate == vector_root or vector_root not in candidate.parents:
        raise ValueError("Vector SVG path is outside the StableAMD Vector output directory.")
    if candidate.suffix.lower() != ".svg":
        raise ValueError("Requested Vector output is not an SVG file.")
    if not candidate.is_file():
        raise ValueError("Vector SVG file was not found.")
    return candidate


# Compatibility export for callers that use the established stableamd_server
# path helpers. Keeping the implementation here prevents Vector from changing
# the accepted base HTTP server lifecycle.
base.resolve_output_svg = resolve_output_svg


def _managed_output_path(repo_root: Path, requested_path: str) -> Path:
    if not requested_path or not str(requested_path).strip():
        raise ValueError("Managed output path is required.")
    output_root = (Path(repo_root).resolve() / ".runtime" / "stableamd" / "output").resolve()
    candidate = Path(requested_path).expanduser().resolve()
    if candidate == output_root or output_root not in candidate.parents:
        raise ValueError("Managed output path is outside the StableAMD output directory.")
    if not candidate.is_file():
        raise ValueError("Managed output file was not found.")
    return candidate


class VectorAssetsBridgeMixin:
    """Safe source/download and deletion lifecycle for persisted Vector SVG assets."""

    def _vector_history_record_for_svg(self, svg_path: Path) -> tuple[Path, dict[str, Any]] | None:
        history_root = (Path(self.repo_root).resolve() / ".runtime" / "stableamd" / "history").resolve()
        if not history_root.is_dir():
            return None
        for history_path in history_root.glob("*.json"):
            try:
                record = json.loads(history_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            if str(record.get("assetType") or "").lower() != "svg" or record.get("sanitized") is not True:
                continue
            raw_svg = str(record.get("svgPath") or "").strip()
            if not raw_svg:
                continue
            try:
                persisted_svg = resolve_output_svg(self.repo_root, raw_svg)
            except ValueError:
                continue
            if persisted_svg == svg_path:
                return history_path.resolve(), record
        return None

    def vector_source(self, requested_path: str) -> dict[str, str]:
        svg_path = resolve_output_svg(self.repo_root, requested_path)
        persisted = self._vector_history_record_for_svg(svg_path)
        if persisted is None:
            raise base.StableAmdBridgeError("Vector SVG is not a persisted sanitized Gallery asset.")
        try:
            source = svg_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise base.StableAmdBridgeError(f"Vector SVG source could not be read: {exc}") from exc

        # A local file may have been changed after generation. Re-run the Clean
        # SVG contract and require exact canonical output before exposing it for
        # source/download.
        sanitized = svg_sanitize.sanitize_svg(source)
        if sanitized.xml != source:
            raise base.StableAmdBridgeError(
                "Vector SVG no longer matches its canonical sanitized representation."
            )
        return {"fileName": svg_path.name, "svg": source}

    def _find_vector_history_by_prompt(self, prompt_id: str) -> tuple[Path, dict[str, Any]] | None:
        history_root = (Path(self.repo_root).resolve() / ".runtime" / "stableamd" / "history").resolve()
        if not history_root.is_dir():
            return None
        for history_path in history_root.glob("*.json"):
            try:
                record = json.loads(history_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            record_prompt = str(record.get("promptId") or record.get("PromptId") or "").strip()
            if record_prompt != prompt_id:
                continue
            if str(record.get("assetType") or "").lower() != "svg":
                return None
            return history_path.resolve(), record
        return None

    def delete_history(self, prompt_id: str) -> dict[str, Any]:
        prompt_id = str(prompt_id or "").strip()
        if not prompt_id:
            raise base.StableAmdBridgeError("History prompt id is required.")

        found = self._find_vector_history_by_prompt(prompt_id)
        if found is None:
            return super().delete_history(prompt_id)

        history_path, record = found
        refused_owned: list[str] = []
        deleted_owned: list[str] = []
        refused_paths: list[str] = []

        raw_svg = str(record.get("svgPath") or "").strip()
        if raw_svg:
            try:
                svg_path = resolve_output_svg(self.repo_root, raw_svg)
                svg_path.unlink(missing_ok=True)
            except ValueError:
                refused_paths.append(raw_svg)
            except OSError as exc:
                raise base.StableAmdBridgeError(f"Could not delete Vector SVG: {exc}") from exc

        raw_preview = str(record.get("previewPath") or "").strip()
        if raw_preview:
            try:
                preview_path = _managed_output_path(self.repo_root, raw_preview)
                preview_path.unlink(missing_ok=True)
            except ValueError:
                refused_paths.append(raw_preview)
            except OSError as exc:
                raise base.StableAmdBridgeError(f"Could not delete Vector preview: {exc}") from exc

        owned = record.get("ownedIntermediatePaths")
        for raw in owned if isinstance(owned, list) else []:
            raw_path = str(raw or "").strip()
            if not raw_path:
                continue
            try:
                path = _managed_output_path(self.repo_root, raw_path)
            except ValueError:
                refused_owned.append(raw_path)
                continue
            try:
                path.unlink(missing_ok=True)
                deleted_owned.append(str(path))
            except OSError as exc:
                raise base.StableAmdBridgeError(f"Could not delete Vector owned intermediate: {exc}") from exc

        try:
            history_path.unlink(missing_ok=True)
        except OSError as exc:
            raise base.StableAmdBridgeError(f"Could not delete Vector Gallery history record: {exc}") from exc

        return {
            "deleted": True,
            "promptId": prompt_id,
            "assetType": "svg",
            "svgDeleted": bool(raw_svg and raw_svg not in refused_paths),
            "previewDeleted": bool(raw_preview and raw_preview not in refused_paths),
            "ownedIntermediateDeleted": deleted_owned,
            "refusedOwnedPaths": refused_owned,
            "refusedPaths": refused_paths,
        }


class VectorAssetsApiMixin:
    """JSON-only access to persisted sanitized SVG source."""

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        method = (method or "").upper()
        parsed = urlsplit(target)
        if method == "GET" and parsed.path == "/api/vector/source":
            requested = parse_qs(parsed.query).get("path", [""])[0]
            try:
                return 200, self.bridge.vector_source(requested)
            except ValueError as exc:
                return 404, {"error": str(exc)}
            except base.StableAmdBridgeError as exc:
                return 409, {"error": str(exc)}
        return super().dispatch(method, target, body)
