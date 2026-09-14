from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, local
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_server as v03

base = v03.base


class PowerShellBridge(v03.PowerShellBridge):
    """v0.3 extension that adds model-only LoRA execution to Z-Image Turbo."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self._zimage_lora_context = local()
        self._zimage_generation_lock = RLock()
        self._zimage_lora_signature: tuple[tuple[str, float], ...] | None = None
        self._zimage_memory_dirty = False

    @staticmethod
    def _combo_choices(payload: Any, node_name: str, input_name: str) -> list[str]:
        choices = base.PowerShellBridge._comfy_choice_list(payload, node_name, input_name)
        if choices:
            return choices
        if not isinstance(payload, dict):
            return []
        node = payload.get(node_name)
        if not isinstance(node, dict):
            return []
        required = node.get("input", {}).get("required", {})
        spec = required.get(input_name) if isinstance(required, dict) else None
        if not isinstance(spec, list) or len(spec) < 2 or spec[0] != "COMBO" or not isinstance(spec[1], dict):
            return []
        options = spec[1].get("options")
        if not isinstance(options, list):
            return []
        return [str(value) for value in options if str(value).strip()]

    def _resolve_zimage_loras(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        stack = request.get("loraStack")
        if not isinstance(stack, list):
            legacy = str(request.get("loraName") or "").strip()
            stack = [] if not legacy else [
                {
                    "name": legacy,
                    "modelStrength": request.get("loraModelStrength", 1.0),
                    "enabled": True,
                }
            ]
        if not stack:
            return []

        info = self._comfy_json("object_info/LoraLoaderModelOnly")
        choices = self._combo_choices(info, "LoraLoaderModelOnly", "lora_name")
        if not choices:
            raise base.StableAmdBridgeError(
                "ComfyUI does not expose LoraLoaderModelOnly or any LoRA choices. Restart StableAMD after changing LoRA roots."
            )
        by_lower = {str(name).replace("\\", "/").lower(): str(name) for name in choices}
        by_leaf: dict[str, list[str]] = {}
        for name in choices:
            leaf = Path(str(name).replace("\\", "/")).name.lower()
            by_leaf.setdefault(leaf, []).append(str(name))

        resolved: list[dict[str, Any]] = []
        for index, entry in enumerate(stack):
            if not isinstance(entry, dict):
                raise base.StableAmdBridgeError(f"LoRA stack entry {index + 1} must be an object.")
            name = str(entry.get("name") or "").strip()
            if not name:
                raise base.StableAmdBridgeError(f"LoRA stack entry {index + 1} does not contain a name.")
            enabled = entry.get("enabled", True) is not False
            try:
                strength = float(entry.get("modelStrength", 1.0))
            except (TypeError, ValueError) as exc:
                raise base.StableAmdBridgeError(f"LoRA stack entry {index + 1} strength must be numeric.") from exc
            if not math.isfinite(strength) or strength < -100 or strength > 100:
                raise base.StableAmdBridgeError("LoRA model strength must be between -100 and 100.")

            resolved_name = name
            if enabled:
                normalized = name.replace("\\", "/").lower()
                resolved_name = by_lower.get(normalized, "")
                if not resolved_name:
                    leaf_matches = by_leaf.get(Path(normalized).name.lower(), [])
                    if len(leaf_matches) == 1:
                        resolved_name = leaf_matches[0]
                if not resolved_name:
                    raise base.StableAmdBridgeError(
                        f"ComfyUI does not expose LoRA '{name}' through LoraLoaderModelOnly. Restart StableAMD after changing LoRA roots."
                    )

            resolved.append(
                {
                    "name": resolved_name or name,
                    "modelStrength": strength,
                    "clipStrength": 0.0,
                    "enabled": enabled,
                }
            )
        return resolved

    def _active_zimage_loras(self) -> list[dict[str, Any]]:
        stack = getattr(self._zimage_lora_context, "stack", None)
        return stack if isinstance(stack, list) else []

    @staticmethod
    def _zimage_stack_signature(stack: list[dict[str, Any]]) -> tuple[tuple[str, float], ...]:
        return tuple(
            (
                str(entry.get("name") or "").replace("\\", "/").lower(),
                float(entry.get("modelStrength", 1.0)),
            )
            for entry in stack
            if entry.get("enabled", True) is not False
        )

    def _release_comfy_memory(self, reason: str) -> None:
        url = self._backend_base_url() + "free"
        body = json.dumps(
            {"unload_models": True, "free_memory": True},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                response.read()
        except (OSError, URLError) as exc:
            raise base.StableAmdBridgeError(
                f"Could not release ComfyUI model/cache memory before Z-Image transition: {exc}"
            ) from exc
        print(f"StableAMD Z-Image memory guard: released ComfyUI models/cache ({reason}).", flush=True)
        # /free is serviced by ComfyUI's prompt worker. Give it a short window
        # to consume the flags before a new large Lumina2 graph is submitted.
        time.sleep(0.35)

    def _prepare_zimage_memory(self, stack: list[dict[str, Any]]) -> None:
        signature = self._zimage_stack_signature(stack)
        changed = self._zimage_lora_signature is not None and signature != self._zimage_lora_signature
        if self._zimage_memory_dirty or changed:
            reasons: list[str] = []
            if self._zimage_memory_dirty:
                reasons.append("previous post-processing changed the resident graph")
            if changed:
                reasons.append("LoRA stack changed")
            self._release_comfy_memory("; ".join(reasons))
            self._zimage_memory_dirty = False
        self._zimage_lora_signature = signature

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        params = list(parameters or [])
        stack = self._active_zimage_loras()
        if name == "Build-StableAmdWorkflow.ps1" and stack:
            family = next((str(value).lower() for key, value in params if key == "Family"), "")
            if family == "z-image-turbo":
                params = [(key, value) for key, value in params if key != "LoraStackJson"]
                params.append(("LoraStackJson", json.dumps(stack, ensure_ascii=False, separators=(",", ":"))))
        return super()._run_script(name, params)

    def _save_zimage_history(self, record: dict[str, Any]) -> Path:
        stack = self._active_zimage_loras()
        if stack:
            enabled = [entry for entry in stack if entry.get("enabled", True)]
            record["loraStack"] = stack
            record["loraName"] = enabled[0]["name"] if len(enabled) == 1 else ""
            record["loraModelStrength"] = enabled[0]["modelStrength"] if len(enabled) == 1 else None
            record["loraClipStrength"] = 0.0 if len(enabled) == 1 else None
        return super()._save_zimage_history(record)

    @staticmethod
    def _history_timestamp(record: dict[str, Any], record_path: Path) -> float:
        raw = str(record.get("createdAtUtc") or record.get("CreatedAtUtc") or "").strip()
        if raw:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except (TypeError, ValueError, OverflowError):
                pass
        try:
            return record_path.stat().st_mtime
        except OSError:
            return 0.0

    def history(self, limit: int = 0) -> list[dict[str, Any]]:
        """Read Gallery records directly so malformed/empty PowerShell output cannot break Gallery."""
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        if not history_root.is_dir():
            return []

        records: list[tuple[float, dict[str, Any]]] = []
        for record_path in history_root.glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            records.append((self._history_timestamp(record, record_path), record))

        records.sort(key=lambda item: item[0], reverse=True)
        result = [record for _, record in records]
        if limit > 0:
            return result[:limit]
        return result

    def delete_history(self, prompt_id: str) -> dict[str, Any]:
        """Delete current and legacy Gallery records without depending on JSON key casing."""
        prompt_id = str(prompt_id or "").strip()
        if not prompt_id:
            raise base.StableAmdBridgeError("History prompt id is required.")

        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        if not history_root.is_dir():
            return {"deleted": False, "promptId": prompt_id, "imageDeleted": False}

        for record_path in history_root.glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue

            record_prompt_id = str(record.get("promptId") or record.get("PromptId") or "").strip()
            if record_prompt_id != prompt_id:
                continue

            image_deleted = False
            raw_image = str(record.get("imagePath") or record.get("ImagePath") or "").strip()
            if raw_image:
                try:
                    image = base.resolve_output_image(self.repo_root, raw_image)
                    image.unlink(missing_ok=True)
                    image_deleted = not image.exists()
                except (ValueError, OSError):
                    # A stale or already missing image must not make its history
                    # record impossible to remove from Gallery.
                    image_deleted = False

            try:
                record_path.unlink(missing_ok=True)
            except OSError as exc:
                raise base.StableAmdBridgeError(f"Could not delete Gallery history record: {exc}") from exc
            return {"deleted": True, "promptId": prompt_id, "imageDeleted": image_deleted}

        return {"deleted": False, "promptId": prompt_id, "imageDeleted": False}

    def upscale(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return super().upscale(request)
        finally:
            # The RRDB/ESRGAN workflow changes ComfyUI's resident graph. The
            # next large Z-Image load should start from a clean model/cache state.
            self._zimage_memory_dirty = True

    def restart_backend(self) -> Any:
        result = super().restart_backend()
        self._zimage_lora_signature = None
        self._zimage_memory_dirty = False
        return result

    def _generate_zimage_turbo(self, request: dict[str, Any], model: dict[str, Any]) -> Any:
        stack = self._resolve_zimage_loras(request)
        clean_request = dict(request)
        clean_request.pop("loraStack", None)
        clean_request.pop("loraName", None)
        clean_request.pop("loraModelStrength", None)
        clean_request.pop("loraClipStrength", None)

        with self._zimage_generation_lock:
            self._prepare_zimage_memory(stack)
            self._zimage_lora_context.stack = stack
            try:
                result = super()._generate_zimage_turbo(clean_request, model)
            finally:
                self._zimage_lora_context.stack = []

        enabled = [entry for entry in stack if entry.get("enabled", True)]
        result["LoraStack"] = stack
        result["LoraName"] = enabled[0]["name"] if len(enabled) == 1 else ""
        result["LoraModelStrength"] = enabled[0]["modelStrength"] if len(enabled) == 1 else None
        result["LoraClipStrength"] = 0.0 if len(enabled) == 1 else None
        return result


# stableamd_v03_server already installs its API extension into the proven base
# server. Replace only the bridge class so all existing v0.3 routes and behavior
# remain unchanged while Z-Image gains model-only LoRA execution.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = v03.StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
