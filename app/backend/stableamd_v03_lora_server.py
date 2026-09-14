from __future__ import annotations

import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import local
from typing import Any

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
                    image_deleted = False

            try:
                record_path.unlink(missing_ok=True)
            except OSError as exc:
                raise base.StableAmdBridgeError(f"Could not delete Gallery history record: {exc}") from exc
            return {"deleted": True, "promptId": prompt_id, "imageDeleted": image_deleted}

        return {"deleted": False, "promptId": prompt_id, "imageDeleted": False}

    def _generate_inpaint(self, request: dict[str, Any]) -> Any:
        edit_context = request.get("editContext") if isinstance(request.get("editContext"), dict) else None
        clean_request = dict(request)
        clean_request.pop("editContext", None)
        result = super()._generate_inpaint(clean_request)
        if not edit_context or edit_context.get("kind") != "outpaint":
            return result

        margins = dict(edit_context.get("margins") or {})
        blend_overlap = int(edit_context.get("blendOverlap") or 0)
        source_prompt_id = str(edit_context.get("sourcePromptId") or "").strip()
        source_image_path = str(edit_context.get("sourceImagePath") or "").strip()
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        raw_history_path = str(result.get("HistoryPath") or "").strip()
        if raw_history_path:
            history_path = Path(raw_history_path).resolve()
            if history_root in history_path.parents and history_path.is_file():
                try:
                    record = json.loads(history_path.read_text(encoding="utf-8-sig"))
                    if isinstance(record, dict):
                        record["mode"] = "outpaint"
                        record["editOperation"] = "outpaint"
                        record["sourcePromptId"] = source_prompt_id
                        record["sourceImagePath"] = source_image_path
                        record["outpaintMargins"] = margins
                        record["outpaintBlendOverlap"] = blend_overlap
                        temporary = history_path.with_suffix(history_path.suffix + f".tmp-{uuid.uuid4().hex}")
                        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                        temporary.replace(history_path)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise base.StableAmdBridgeError(f"Outpaint completed, but its Gallery metadata could not be updated: {exc}") from exc

        result["Mode"] = "outpaint"
        result["EditOperation"] = "outpaint"
        result["SourcePromptId"] = source_prompt_id
        result["SourceImagePath"] = source_image_path
        result["OutpaintMargins"] = margins
        result["OutpaintBlendOverlap"] = blend_overlap
        return result

    def _generate_zimage_turbo(self, request: dict[str, Any], model: dict[str, Any]) -> Any:
        # Keep the plain generation path identical to the target-machine-proven
        # 985845e4 behavior. In particular, do not call ComfyUI /free or force a
        # graph unload before a generation: after the first native Lumina crash,
        # subsequent runs on the target machine became unstable even after the
        # process was restarted.
        stack = self._resolve_zimage_loras(request)
        clean_request = dict(request)
        clean_request.pop("loraStack", None)
        clean_request.pop("loraName", None)
        clean_request.pop("loraModelStrength", None)
        clean_request.pop("loraClipStrength", None)

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


class StableAmdApi(v03.StableAmdApi):
    _generation_fields = set(v03.StableAmdApi._generation_fields) | {"editContext"}

    @staticmethod
    def _validate_edit_context(value: Any) -> None:
        if not isinstance(value, dict):
            raise ValueError("editContext must be an object.")
        unsupported = sorted(set(value) - {"kind", "sourcePromptId", "sourceImagePath", "margins", "blendOverlap"})
        if unsupported:
            raise ValueError("Unsupported editContext field(s): " + ", ".join(unsupported))
        if value.get("kind") != "outpaint":
            raise ValueError("editContext kind must be 'outpaint'.")
        for field in ("sourcePromptId", "sourceImagePath"):
            if field in value and not isinstance(value[field], str):
                raise ValueError(f"editContext {field} must be a string.")

        blend = value.get("blendOverlap", 0)
        if isinstance(blend, bool) or not isinstance(blend, (int, float)) or not math.isfinite(float(blend)):
            raise ValueError("Outpaint blendOverlap must be numeric.")
        if blend < 0 or blend > 256 or int(blend) != blend or int(blend) % 8 != 0:
            raise ValueError("Outpaint blendOverlap must be an integer from 0 to 256 divisible by 8.")

        margins = value.get("margins")
        if not isinstance(margins, dict):
            raise ValueError("Outpaint editContext requires margins.")
        if set(margins) != {"left", "right", "top", "bottom"}:
            raise ValueError("Outpaint margins must contain left, right, top and bottom.")
        total = 0
        for side in ("left", "right", "top", "bottom"):
            amount = margins[side]
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(float(amount)):
                raise ValueError(f"Outpaint margin '{side}' must be numeric.")
            if amount < 0 or amount > 1024 or int(amount) != amount or int(amount) % 8 != 0:
                raise ValueError(f"Outpaint margin '{side}' must be an integer from 0 to 1024 divisible by 8.")
            total += int(amount)
        if total <= 0:
            raise ValueError("Outpaint requires at least one non-zero margin.")

    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        validated = super()._validate_generation(request)
        if "editContext" in validated:
            if str(validated.get("mode") or "") != "inpaint":
                raise ValueError("editContext is valid only for inpaint/outpaint generation.")
            self._validate_edit_context(validated["editContext"])
        return validated


# stableamd_v03_server already installs its API extension into the proven base
# server. Replace only the bridge/API extension points so all existing v0.3
# routes remain unchanged while Z-Image gains model-only LoRA execution and
# outpaint results keep their Gallery source relationship.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())