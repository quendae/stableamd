from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from threading import local
from typing import Any

# The managed Windows runtime uses the embeddable Python distribution with a
# restricted module search path. stableamd_v03_server and the native-edit base
# already bootstrap their sibling backend modules explicitly; the final wrapper
# must do the same before importing the renamed edit base.
BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server_base as editing
from curated_model_patches import (
    CuratedModelPatchError,
    install_curated_model_patch,
    public_catalog as public_model_patch_catalog,
)

# Re-export the accepted native-edit contract so existing imports/tests keep the
# same public module surface while dependency installation is layered on top.
base = editing.base
features = editing.features
ZIMAGE_FUN_PATCH = editing.ZIMAGE_FUN_PATCH
ZIMAGE_FUN_LEGACY_PATCH = editing.ZIMAGE_FUN_LEGACY_PATCH
ZIMAGE_FUN_PATCH_SHA256 = editing.ZIMAGE_FUN_PATCH_SHA256
ZIMAGE_FUN_PATCH_BYTES = editing.ZIMAGE_FUN_PATCH_BYTES

_POWERSHELL_JSON_SENTINEL = "__STABLEAMD_JSON__"
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class PowerShellBridge(editing.PowerShellBridge):
    """Final v0.3 product bridge with curated dependencies and Krea 2 LoRA."""

    def __post_init__(self) -> None:
        requested_powershell = self.powershell
        super().__post_init__()

        # StableAMD's target-machine development shell and CI both use
        # PowerShell 7. Prefer pwsh when the application chooses the executable
        # automatically. Windows PowerShell 5.1 remains a fallback for machines
        # where pwsh is not installed.
        if requested_powershell is None:
            preferred = shutil.which("pwsh.exe") or shutil.which("pwsh")
            if preferred:
                self.powershell = preferred

        self._krea_lora_context = local()

    def _registered_model_patches(self) -> list[str]:
        try:
            info = self._comfy_json("object_info/ModelPatchLoader")
        except base.StableAmdBridgeError:
            return []
        return self._combo_choices(info, "ModelPatchLoader", "name")

    def curated_model_patches(self) -> dict[str, Any]:
        root = (self.repo_root / ".runtime" / "stableamd" / "models" / "model_patches").resolve()
        try:
            models = public_model_patch_catalog(self.repo_root, self._registered_model_patches())
        except CuratedModelPatchError as exc:
            raise base.StableAmdBridgeError(str(exc)) from exc
        return {"root": str(root), "models": models}

    def install_curated_model_patch(self, model_id: str) -> dict[str, Any]:
        try:
            return install_curated_model_patch(
                self.repo_root,
                model_id,
                registered_patches=self._registered_model_patches(),
            )
        except CuratedModelPatchError as exc:
            raise base.StableAmdBridgeError(str(exc)) from exc

    def _active_krea_loras(self) -> list[dict[str, Any]]:
        stack = getattr(self._krea_lora_context, "stack", None)
        return stack if isinstance(stack, list) else []

    def _resolve_krea_loras(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        # Krea 2's official ComfyUI workflow applies adapters to MODEL only via
        # LoraLoaderModelOnly. Reuse the already-proven resolver used by
        # Z-Image: it validates the same node choices, strengths and stack
        # contract while forcing CLIP strength to zero.
        return self._resolve_zimage_loras(request)

    @staticmethod
    def _powershell_parameter_tokens(parameters: list[tuple[str, Any]] | None) -> list[str]:
        parts: list[str] = []
        for key, value in parameters or []:
            if value is None or value is False:
                continue
            parts.append(f"-{key}")
            if value is True:
                continue
            if isinstance(value, bool):
                parts.append("$true" if value else "$false")
            elif isinstance(value, (int, float)):
                parts.append(str(value))
            else:
                parts.append(base._powershell_literal(str(value)))
        return parts

    @staticmethod
    def _sanitize_powershell_json(payload: str) -> str:
        # PowerShell warning/progress rendering can leak ANSI CSI sequences into
        # captured stdout. A source-encoding mismatch can also surface C0 bytes
        # such as BEL inside an otherwise valid JSON string. Neither should make
        # the product lose all model discovery. Keep JSON whitespace, strip the
        # remaining C0 transport noise, then parse the cleaned payload.
        cleaned = _ANSI_ESCAPE_RE.sub("", str(payload or ""))
        cleaned = "".join(ch for ch in cleaned if ch in "\t\r\n" or ord(ch) >= 0x20)
        return cleaned.strip()

    @classmethod
    def _parse_powershell_json(cls, stdout: str) -> Any:
        lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]

        # Preferred v0.3 contract. The sentinel makes parsing deterministic even
        # when PowerShell modules print warnings, progress, verbose messages or
        # other host output before the actual machine-readable payload.
        for line in reversed(lines):
            marker = line.find(_POWERSHELL_JSON_SENTINEL)
            if marker < 0:
                continue
            payload = cls._sanitize_powershell_json(line[marker + len(_POWERSHELL_JSON_SENTINEL) :])
            if not payload:
                return None
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                # strict=False is a final compatibility guard for malformed C0
                # characters embedded by external scripts that survived string
                # transport. Our own scripts should never require this path.
                try:
                    return json.loads(payload, strict=False)
                except json.JSONDecodeError:
                    continue

        # Backward-compatible parser for explicit/custom PowerShell commands and
        # old scripts that may still emit a clean JSON line without the marker.
        for line in reversed(lines):
            payload = cls._sanitize_powershell_json(line)
            if payload.startswith("{") or payload.startswith("[") or payload in {"null", "true", "false"}:
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    try:
                        return json.loads(payload, strict=False)
                    except json.JSONDecodeError:
                        continue
        raise ValueError("no machine-readable JSON payload found")

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        script = self._script_path(name)
        invocation = [
            "&",
            base._powershell_literal(str(script)),
            "-RepoRoot",
            base._powershell_literal(str(self.repo_root)),
            *self._powershell_parameter_tokens(parameters),
        ]
        invoke_text = " ".join(invocation)

        # Force terminating failures and wrap the script output in a unique JSON
        # envelope. Convert the whole success-stream result at once so arrays,
        # objects and scalar/null results all share the same transport contract.
        # Warnings/progress are intentionally suppressed for this machine-facing
        # transport; actionable failures still become terminating exceptions.
        command = (
            "$ErrorActionPreference = 'Stop'; "
            "$WarningPreference = 'SilentlyContinue'; "
            "$ProgressPreference = 'SilentlyContinue'; "
            "try { "
            f"$stableamdPayload = @({invoke_text}); "
            "$stableamdJson = $stableamdPayload | ConvertTo-Json -Depth 20 -Compress; "
            "if ($null -eq $stableamdJson) { $stableamdJson = 'null' }; "
            f"Write-Output ('{_POWERSHELL_JSON_SENTINEL}' + $stableamdJson); "
            "} catch { "
            "[Console]::Error.WriteLine(($_ | Out-String)); exit 1 "
            "}"
        )

        completed = subprocess.run(
            [
                str(self.powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "PowerShell command failed").strip()
            executable = Path(str(self.powershell)).name or str(self.powershell)
            raise base.StableAmdBridgeError(
                f"StableAMD PowerShell script '{name}' failed via {executable}: {detail[-8000:]}"
            )

        try:
            result = self._parse_powershell_json(completed.stdout)
        except ValueError as exc:
            executable = Path(str(self.powershell)).name or str(self.powershell)
            stdout_tail = str(completed.stdout or "").strip()[-4000:]
            stderr_tail = str(completed.stderr or "").strip()[-4000:]
            detail = stdout_tail or stderr_tail or "<no output>"
            raise base.StableAmdBridgeError(
                f"StableAMD PowerShell script '{name}' via {executable} returned no machine-readable JSON. "
                f"Output tail: {detail}"
            ) from exc

        stack = self._active_krea_loras()
        if name != "Build-StableAmdWorkflow.ps1" or not stack or not isinstance(result, dict):
            return result

        params = list(parameters or [])
        family = next((str(value).lower() for key, value in params if key == "Family"), "")
        if family != "krea2":
            return result

        # Official Krea 2 Turbo workflow: UNETLoader -> optional ordered
        # LoraLoaderModelOnly chain -> KSampler. The text encoder is unchanged.
        model_ref: list[Any] = ["10", 0]
        applied = 0
        for entry in stack:
            if entry.get("enabled", True) is False:
                continue
            node_id = str(40 + applied)
            result[node_id] = {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "lora_name": str(entry["name"]),
                    "strength_model": float(entry.get("modelStrength", 1.0)),
                    "model": model_ref,
                },
            }
            model_ref = [node_id, 0]
            applied += 1

        if applied:
            sampler = result.get("3")
            if not isinstance(sampler, dict) or not isinstance(sampler.get("inputs"), dict):
                raise base.StableAmdBridgeError("Krea 2 workflow is missing its KSampler model input.")
            sampler["inputs"]["model"] = model_ref
        return result

    def _persist_krea_lora_history(self, result: dict[str, Any], stack: list[dict[str, Any]]) -> None:
        raw_history = str(result.get("HistoryPath") or "").strip()
        if not raw_history:
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        path = Path(raw_history).resolve()
        if history_root not in path.parents or not path.is_file():
            return

        enabled = [entry for entry in stack if entry.get("enabled", True) is not False]
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record["loraStack"] = stack
            record["loraName"] = enabled[0]["name"] if len(enabled) == 1 else ""
            record["loraModelStrength"] = enabled[0]["modelStrength"] if len(enabled) == 1 else None
            record["loraClipStrength"] = 0.0 if len(enabled) == 1 else None
            temporary = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex}")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise base.StableAmdBridgeError(
                f"Krea 2 generation completed, but its LoRA Gallery metadata could not be updated: {exc}"
            ) from exc

    def _generate_krea2_turbo(self, request: dict[str, Any], model: dict[str, Any]) -> Any:
        stack = self._resolve_krea_loras(request)
        clean_request = dict(request)
        clean_request.pop("loraStack", None)
        clean_request.pop("loraName", None)
        clean_request.pop("loraModelStrength", None)
        clean_request.pop("loraClipStrength", None)

        self._krea_lora_context.stack = stack
        try:
            result = super()._generate_krea2_turbo(clean_request, model)
        finally:
            self._krea_lora_context.stack = []

        enabled = [entry for entry in stack if entry.get("enabled", True) is not False]
        result["LoraStack"] = stack
        result["LoraName"] = enabled[0]["name"] if len(enabled) == 1 else ""
        result["LoraModelStrength"] = enabled[0]["modelStrength"] if len(enabled) == 1 else None
        result["LoraClipStrength"] = 0.0 if len(enabled) == 1 else None
        if stack:
            self._persist_krea_lora_history(result, stack)
        return result


class StableAmdApi(editing.StableAmdApi):
    _curated_model_patch_install_fields = {"id"}

    def _validate_curated_model_patch_install(self, request: dict[str, Any]) -> str:
        unsupported = sorted(set(request) - self._curated_model_patch_install_fields)
        if unsupported:
            raise ValueError("Unsupported curated model patch install field(s): " + ", ".join(unsupported))
        model_id = request.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("Curated model patch id is required.")
        return model_id.strip()

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        try:
            if method == "GET" and path == "/api/model-patches/catalog":
                return 200, self.bridge.curated_model_patches()
            if method == "POST" and path == "/api/model-patches/install":
                model_id = self._validate_curated_model_patch_install(self._decode_json(body))
                return 200, self.bridge.install_curated_model_patch(model_id)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return super().dispatch(method, target, body)


# The renamed base module installs the accepted edit-aware classes first.
# Replace only the final extension points with the dependency-aware subclasses.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
