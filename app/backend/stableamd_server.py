from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen

from model_support import load_model_support_catalog, summarize_model_support

SERVICE_NAME = "StableAMD"
API_VERSION = 3
MAX_REQUEST_BYTES = 1024 * 1024
SUPPORTED_OUTPUT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
BUNDLE_ASSET_ROLES = ("diffusion_model", "text_encoder", "vae")


class StableAmdBridgeError(RuntimeError):
    pass


def validate_loopback_host(host: str) -> str:
    normalized = (host or "").strip().lower()
    if normalized in {"127.0.0.1", "localhost"}:
        return "127.0.0.1"
    if normalized == "::1":
        return "::1"
    raise ValueError("StableAMD may bind only to a loopback host.")


def resolve_output_image(repo_root: Path, requested_path: str) -> Path:
    if not requested_path or not str(requested_path).strip():
        raise ValueError("Generated image path is required.")

    root = (Path(repo_root).resolve() / ".runtime" / "stableamd" / "output").resolve()
    candidate = Path(requested_path).expanduser().resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Generated image path is outside the StableAMD output directory.")
    if candidate.suffix.lower() not in SUPPORTED_OUTPUT_IMAGE_SUFFIXES:
        raise ValueError("Requested output is not a supported image type.")
    if not candidate.is_file():
        raise ValueError("Generated image file was not found.")
    return candidate


def _powershell_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@dataclass
class PowerShellBridge:
    repo_root: Path
    powershell: str | None = None

    def __post_init__(self) -> None:
        self.repo_root = Path(self.repo_root).resolve()
        if self.powershell is None:
            self.powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
        if not self.powershell:
            raise StableAmdBridgeError("PowerShell was not found on PATH.")

    @property
    def scripts_root(self) -> Path:
        return self.repo_root / "scripts"

    def _script_path(self, name: str) -> Path:
        path = (self.scripts_root / name).resolve()
        if path.parent != self.scripts_root.resolve() or not path.is_file():
            raise StableAmdBridgeError(f"Required StableAMD script is missing: {path}")
        return path

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        script = self._script_path(name)
        parts = ["&", _powershell_literal(str(script)), "-RepoRoot", _powershell_literal(str(self.repo_root))]
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
                parts.append(_powershell_literal(str(value)))
        command = " ".join(parts) + " | ConvertTo-Json -Depth 20 -Compress"

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
            raise StableAmdBridgeError(detail[-8000:])

        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        for line in reversed(lines):
            if line.startswith("{") or line.startswith("[") or line in {"null", "true", "false"}:
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        if not lines:
            return None
        raise StableAmdBridgeError("StableAMD PowerShell service did not return machine-readable JSON.")

    def status(self) -> Any:
        return self._run_script("Get-StableAMDStatus.ps1")

    @staticmethod
    def _normalize_model_payload(result: Any) -> list[Any]:
        if result is None:
            return []
        if isinstance(result, dict):
            if "models" in result:
                nested = result.get("models")
                if nested is None:
                    return []
                return nested if isinstance(nested, list) else [nested]
            if "value" in result and "Count" in result:
                nested = result.get("value")
                if nested is None:
                    return []
                return nested if isinstance(nested, list) else [nested]
        return result if isinstance(result, list) else [result]

    @staticmethod
    def _normalize_list_payload(result: Any) -> list[Any]:
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def models(self) -> Any:
        return self._normalize_model_payload(self._run_script("List-Models.ps1"))

    def scan_models(self) -> Any:
        return self.models()

    def model_roots(self) -> Any:
        return self._normalize_list_payload(self._run_script("Get-ModelRoots.ps1"))

    def browse_model_root(self) -> Any:
        result = self._run_script("Browse-ModelRoot.ps1")
        return result or {"cancelled": True, "path": None}

    def lora_roots(self) -> Any:
        return self._normalize_list_payload(self._run_script("Get-LoraRoots.ps1"))

    def browse_lora_root(self) -> Any:
        result = self._run_script("Browse-LoraRoot.ps1")
        return result or {"cancelled": True, "path": None}

    def bundle_roots(self) -> dict[str, list[Any]]:
        return {
            role: self._normalize_list_payload(self._run_script("Get-BundleAssetRoots.ps1", [("Role", role)]))
            for role in BUNDLE_ASSET_ROLES
        }

    def browse_bundle_root(self, role: str) -> Any:
        result = self._run_script("Browse-BundleAssetRoot.ps1", [("Role", role)])
        return result or {"cancelled": True, "role": role, "path": None}

    def _backend_restart_required(self) -> bool:
        status = self.status()
        return isinstance(status, dict) and bool(status.get("Healthy", status.get("healthy", False)))

    def add_model_root(self, path: str) -> Any:
        result = self._run_script("Add-ModelRoot.ps1", [("Path", path)]) or {}
        restart_required = bool(isinstance(result, dict) and result.get("added") and self._backend_restart_required())
        models = self.models()
        if isinstance(result, dict):
            return {**result, "restartRequired": restart_required, "models": models}
        return {"added": False, "path": path, "restartRequired": False, "models": models}

    def remove_model_root(self, path: str) -> Any:
        result = self._run_script("Remove-ModelRoot.ps1", [("Path", path)]) or {}
        restart_required = bool(isinstance(result, dict) and result.get("removed") and self._backend_restart_required())
        models = self.models()
        if isinstance(result, dict):
            return {**result, "restartRequired": restart_required, "models": models}
        return {"removed": False, "path": path, "restartRequired": False, "models": models}

    def add_lora_root(self, path: str) -> Any:
        result = self._run_script("Add-LoraRoot.ps1", [("Path", path)]) or {}
        restart_required = bool(isinstance(result, dict) and result.get("added") and self._backend_restart_required())
        if isinstance(result, dict):
            return {**result, "restartRequired": restart_required}
        return {"added": False, "path": path, "restartRequired": False}

    def remove_lora_root(self, path: str) -> Any:
        result = self._run_script("Remove-LoraRoot.ps1", [("Path", path)]) or {}
        restart_required = bool(isinstance(result, dict) and result.get("removed") and self._backend_restart_required())
        if isinstance(result, dict):
            return {**result, "restartRequired": restart_required}
        return {"removed": False, "path": path, "restartRequired": False}

    def add_bundle_root(self, role: str, path: str) -> Any:
        result = self._run_script("Add-BundleAssetRoot.ps1", [("Role", role), ("Path", path)]) or {}
        restart_required = bool(isinstance(result, dict) and result.get("added") and self._backend_restart_required())
        if isinstance(result, dict):
            return {**result, "restartRequired": restart_required}
        return {"added": False, "role": role, "path": path, "restartRequired": False}

    def remove_bundle_root(self, role: str, path: str) -> Any:
        result = self._run_script("Remove-BundleAssetRoot.ps1", [("Role", role), ("Path", path)]) or {}
        restart_required = bool(isinstance(result, dict) and result.get("removed") and self._backend_restart_required())
        if isinstance(result, dict):
            return {**result, "restartRequired": restart_required}
        return {"removed": False, "role": role, "path": path, "restartRequired": False}

    def install_model(self, request: dict[str, Any]) -> Any:
        source = str(request["source"]).lower()
        parameters: list[tuple[str, Any]] = []
        if source == "local":
            parameters.append(("LocalPath", request["localPath"]))
            if request.get("moveLocal"):
                parameters.append(("MoveLocal", True))
        else:
            parameters.extend(
                [
                    ("HuggingFaceRepository", request["repository"]),
                    ("HuggingFaceFilename", request["filename"]),
                    ("Revision", request.get("revision") or "main"),
                ]
            )
            if request.get("token"):
                parameters.append(("HuggingFaceToken", request["token"]))
        if request.get("expectedSha256"):
            parameters.append(("ExpectedSha256", request["expectedSha256"]))
        return self._run_script("Install-Model.ps1", parameters)

    def history(self, limit: int = 0) -> Any:
        parameters: list[tuple[str, Any]] = []
        if limit > 0:
            parameters.append(("Limit", limit))
        result = self._run_script("Get-GenerationHistory.ps1", parameters)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def generation_profiles(self) -> dict[str, Any]:
        path = self.repo_root / "config" / "generation-profiles.v0.2.json"
        if not path.is_file():
            raise StableAmdBridgeError(f"Generation profile catalog is missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StableAmdBridgeError(f"Generation profile catalog is invalid: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
            raise StableAmdBridgeError("Generation profile catalog must contain a profiles array.")
        return payload

    def model_support(self) -> dict[str, Any]:
        try:
            catalog = load_model_support_catalog(self.repo_root)
            models = [model for model in self.models() if isinstance(model, dict)]
            return summarize_model_support(catalog, models)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise StableAmdBridgeError(f"Model support catalog is invalid: {exc}") from exc

    def _backend_base_url(self) -> str:
        status = self.status()
        if not isinstance(status, dict) or not bool(status.get("Healthy", status.get("healthy", False))):
            raise StableAmdBridgeError("StableAMD compute backend is not healthy.")
        raw_url = str(status.get("Url", status.get("url", ""))).strip()
        parsed = urlsplit(raw_url)
        if parsed.scheme != "http" or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
            raise StableAmdBridgeError("StableAMD backend state did not contain a safe loopback URL.")
        return raw_url.rstrip("/") + "/"

    def _comfy_json(self, relative_path: str) -> Any:
        url = self._backend_base_url() + relative_path.lstrip("/")
        try:
            with urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StableAmdBridgeError(f"Could not read ComfyUI generation metadata: {exc}") from exc

    @staticmethod
    def _comfy_choice_list(payload: Any, node_name: str, input_name: str) -> list[str]:
        if not isinstance(payload, dict):
            return []
        node = payload.get(node_name)
        if not isinstance(node, dict):
            return []
        required = node.get("input", {}).get("required", {})
        spec = required.get(input_name)
        if not isinstance(spec, list) or not spec:
            return []
        choices = spec[0]
        if not isinstance(choices, list):
            return []
        return [str(value) for value in choices if str(value).strip()]

    def generation_options(self) -> dict[str, list[str]]:
        ksampler = self._comfy_json("object_info/KSampler")
        lora_loader = self._comfy_json("object_info/LoraLoader")
        return {
            "samplers": self._comfy_choice_list(ksampler, "KSampler", "sampler_name"),
            "schedulers": self._comfy_choice_list(ksampler, "KSampler", "scheduler"),
            "loras": self._comfy_choice_list(lora_loader, "LoraLoader", "lora_name"),
        }

    def generate(self, request: dict[str, Any]) -> Any:
        parameters: list[tuple[str, Any]] = [("Prompt", request["prompt"])]
        mapping = {
            "negativePrompt": "NegativePrompt",
            "modelId": "ModelId",
            "width": "Width",
            "height": "Height",
            "steps": "Steps",
            "cfg": "Cfg",
            "seed": "Seed",
            "samplerName": "SamplerName",
            "scheduler": "Scheduler",
            "loraName": "LoraName",
            "loraModelStrength": "LoraModelStrength",
            "loraClipStrength": "LoraClipStrength",
            "startBackendIfNeeded": "StartBackendIfNeeded",
        }
        for source, target in mapping.items():
            if source in request:
                parameters.append((target, request[source]))
        if "loraStack" in request:
            parameters.append(("LoraStackJson", json.dumps(request["loraStack"], ensure_ascii=False, separators=(",", ":"))))
        return self._run_script("Invoke-Txt2Img.ps1", parameters)

    def start_backend(self) -> Any:
        return self._run_script("Start-StableAMD.ps1")

    def restart_backend(self) -> Any:
        return self._run_script("Start-StableAMD.ps1", [("ForceRestart", True)])

    def stop_backend(self) -> Any:
        return self._run_script("Stop-StableAMD.ps1", [("BackendOnly", True)])

    def diagnostics(self) -> dict[str, Any]:
        log_root = self.repo_root / ".runtime" / "stableamd" / "logs"
        logs: list[dict[str, Any]] = []
        if log_root.is_dir():
            files = sorted(
                (path for path in log_root.glob("*.log") if path.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:8]
            for path in files:
                stat = path.stat()
                logs.append(
                    {
                        "name": path.name,
                        "path": str(path.resolve()),
                        "sizeBytes": stat.st_size,
                        "modifiedAtUtc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    }
                )
        return {"runtime": self.status(), "logs": logs}


class StableAmdApi:
    _generation_fields = {
        "prompt",
        "negativePrompt",
        "modelId",
        "width",
        "height",
        "steps",
        "cfg",
        "seed",
        "samplerName",
        "scheduler",
        "loraName",
        "loraModelStrength",
        "loraClipStrength",
        "loraStack",
        "startBackendIfNeeded",
    }
    _local_model_fields = {"source", "localPath", "moveLocal", "expectedSha256"}
    _huggingface_model_fields = {"source", "repository", "filename", "revision", "token", "expectedSha256"}
    _root_fields = {"path"}
    _bundle_root_fields = {"role", "path"}
    _bundle_browse_fields = {"role"}
    _lora_stack_fields = {"name", "modelStrength", "clipStrength", "enabled"}

    def __init__(self, bridge: Any):
        self.bridge = bridge

    @staticmethod
    def _decode_json(body: bytes | bytearray | None) -> dict[str, Any]:
        if not body:
            return {}
        try:
            value = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must contain valid UTF-8 JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    @staticmethod
    def _required_text(request: dict[str, Any], field: str) -> str:
        value = request.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Model install field '{field}' must be a non-empty string.")
        return value.strip()

    def _validate_root(self, request: dict[str, Any], label: str) -> str:
        unsupported = sorted(set(request) - self._root_fields)
        if unsupported:
            raise ValueError(f"Unsupported {label} folder field(s): " + ", ".join(unsupported))
        value = request.get("path")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} folder path must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _validate_bundle_role(value: Any) -> str:
        if not isinstance(value, str) or value not in BUNDLE_ASSET_ROLES:
            raise ValueError("Bundle asset role must be one of: diffusion_model, text_encoder, vae.")
        return value

    def _validate_bundle_browse(self, request: dict[str, Any]) -> str:
        unsupported = sorted(set(request) - self._bundle_browse_fields)
        if unsupported:
            raise ValueError("Unsupported bundle folder field(s): " + ", ".join(unsupported))
        return self._validate_bundle_role(request.get("role"))

    def _validate_bundle_root(self, request: dict[str, Any]) -> tuple[str, str]:
        unsupported = sorted(set(request) - self._bundle_root_fields)
        if unsupported:
            raise ValueError("Unsupported bundle folder field(s): " + ", ".join(unsupported))
        role = self._validate_bundle_role(request.get("role"))
        path = request.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Bundle asset folder path must be a non-empty string.")
        return role, path.strip()

    def _validate_model_install(self, request: dict[str, Any]) -> dict[str, Any]:
        source = self._required_text(request, "source").lower()
        if source == "local":
            allowed = self._local_model_fields
            self._required_text(request, "localPath")
            if "moveLocal" in request and not isinstance(request["moveLocal"], bool):
                raise ValueError("Model install field 'moveLocal' must be boolean.")
        elif source == "huggingface":
            allowed = self._huggingface_model_fields
            self._required_text(request, "repository")
            filename = self._required_text(request, "filename")
            if not filename.lower().endswith(".safetensors"):
                raise ValueError("Hugging Face filename must identify a .safetensors checkpoint.")
            if "revision" in request and request["revision"] is not None and not isinstance(request["revision"], str):
                raise ValueError("Model install field 'revision' must be a string.")
            if "token" in request and request["token"] is not None and not isinstance(request["token"], str):
                raise ValueError("Model install field 'token' must be a string.")
        else:
            raise ValueError("Model install source must be 'local' or 'huggingface'.")

        unsupported = sorted(set(request) - allowed)
        if unsupported:
            raise ValueError("Unsupported model install field(s): " + ", ".join(unsupported))
        expected = request.get("expectedSha256")
        if expected not in {None, ""}:
            if not isinstance(expected, str) or len(expected.strip()) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected.strip()):
                raise ValueError("expectedSha256 must be a 64-character hexadecimal SHA-256 value.")
        request["source"] = source
        return request

    @staticmethod
    def _validate_numeric_strength(value: Any, field: str) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be numeric.")
        if value < -100 or value > 100:
            raise ValueError(f"{field} must be between -100 and 100.")

    def _validate_lora_stack(self, request: dict[str, Any]) -> None:
        if "loraStack" not in request:
            return
        stack = request["loraStack"]
        if not isinstance(stack, list):
            raise ValueError("loraStack must be an array.")
        if len(stack) > 8:
            raise ValueError("loraStack may contain at most 8 entries.")
        if stack and isinstance(request.get("loraName"), str) and request["loraName"].strip():
            raise ValueError("Use loraStack or legacy loraName, not both.")

        for index, entry in enumerate(stack, start=1):
            if not isinstance(entry, dict):
                raise ValueError(f"loraStack entry {index} must be an object.")
            unsupported = sorted(set(entry) - self._lora_stack_fields)
            if unsupported:
                raise ValueError(f"Unsupported loraStack entry field(s) at {index}: " + ", ".join(unsupported))
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"loraStack entry {index} name must be a non-empty string.")
            if "enabled" in entry and not isinstance(entry["enabled"], bool):
                raise ValueError(f"loraStack entry {index} enabled must be boolean.")
            for field in ("modelStrength", "clipStrength"):
                if field in entry:
                    self._validate_numeric_strength(entry[field], f"loraStack entry {index} {field}")

    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        unsupported = sorted(set(request) - self._generation_fields)
        if unsupported:
            raise ValueError("Unsupported generation field(s): " + ", ".join(unsupported))
        prompt = request.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Generation prompt must be a non-empty string.")
        if "loraName" in request and request["loraName"] is not None and not isinstance(request["loraName"], str):
            raise ValueError("loraName must be a string.")
        for field in ("loraModelStrength", "loraClipStrength"):
            if field in request:
                self._validate_numeric_strength(request[field], field)
        self._validate_lora_stack(request)
        return request

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        method = (method or "").upper()
        parsed = urlsplit(target)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if method == "GET" and path == "/api/health":
                return 200, {"service": SERVICE_NAME, "apiVersion": API_VERSION, "status": "ok"}
            if method == "GET" and path == "/api/status":
                return 200, self.bridge.status()
            if method == "GET" and path == "/api/generation-options":
                return 200, self.bridge.generation_options()
            if method == "GET" and path == "/api/generation-profiles":
                return 200, self.bridge.generation_profiles()
            if method == "GET" and path == "/api/model-support":
                return 200, self.bridge.model_support()
            if method == "GET" and path == "/api/models":
                return 200, self.bridge.models()
            if method == "POST" and path == "/api/models/scan":
                self._decode_json(body)
                return 200, self.bridge.scan_models()
            if method == "GET" and path == "/api/model-roots":
                return 200, self.bridge.model_roots()
            if method == "POST" and path == "/api/model-roots/browse":
                self._decode_json(body)
                return 200, self.bridge.browse_model_root()
            if method == "POST" and path == "/api/model-roots":
                root = self._validate_root(self._decode_json(body), "Model")
                return 200, self.bridge.add_model_root(root)
            if method == "POST" and path == "/api/model-roots/remove":
                root = self._validate_root(self._decode_json(body), "Model")
                return 200, self.bridge.remove_model_root(root)
            if method == "GET" and path == "/api/lora-roots":
                return 200, self.bridge.lora_roots()
            if method == "POST" and path == "/api/lora-roots/browse":
                self._decode_json(body)
                return 200, self.bridge.browse_lora_root()
            if method == "POST" and path == "/api/lora-roots":
                root = self._validate_root(self._decode_json(body), "LoRA")
                return 200, self.bridge.add_lora_root(root)
            if method == "POST" and path == "/api/lora-roots/remove":
                root = self._validate_root(self._decode_json(body), "LoRA")
                return 200, self.bridge.remove_lora_root(root)
            if method == "GET" and path == "/api/bundle-roots":
                return 200, self.bridge.bundle_roots()
            if method == "POST" and path == "/api/bundle-roots/browse":
                role = self._validate_bundle_browse(self._decode_json(body))
                return 200, self.bridge.browse_bundle_root(role)
            if method == "POST" and path == "/api/bundle-roots":
                role, root = self._validate_bundle_root(self._decode_json(body))
                return 200, self.bridge.add_bundle_root(role, root)
            if method == "POST" and path == "/api/bundle-roots/remove":
                role, root = self._validate_bundle_root(self._decode_json(body))
                return 200, self.bridge.remove_bundle_root(role, root)
            if method == "POST" and path == "/api/models/install":
                request = self._validate_model_install(self._decode_json(body))
                return 200, self.bridge.install_model(request)
            if method == "GET" and path == "/api/history":
                raw_limit = query.get("limit", ["0"])[0]
                try:
                    limit = int(raw_limit)
                except (TypeError, ValueError):
                    return 400, {"error": "History limit must be an integer."}
                if limit < 0 or limit > 10000:
                    return 400, {"error": "History limit must be between 0 and 10000."}
                return 200, self.bridge.history(limit=limit)
            if method == "GET" and path == "/api/diagnostics":
                return 200, self.bridge.diagnostics()
            if method == "POST" and path == "/api/backend/start":
                self._decode_json(body)
                return 200, self.bridge.start_backend()
            if method == "POST" and path == "/api/backend/restart":
                self._decode_json(body)
                return 200, self.bridge.restart_backend()
            if method == "POST" and path == "/api/backend/stop":
                self._decode_json(body)
                return 200, self.bridge.stop_backend()
            if method == "POST" and path == "/api/generate":
                request = self._validate_generation(self._decode_json(body))
                return 200, self.bridge.generate(request)
        except ValueError as exc:
            return 400, {"error": str(exc)}

        return 404, {"error": "API route not found."}


def make_handler(api: StableAmdApi, frontend_root: Path | None = None, repo_root: Path | None = None):
    static_root = Path(frontend_root).resolve() if frontend_root is not None else None
    resolved_repo_root = Path(repo_root).resolve() if repo_root is not None else None

    class StableAmdRequestHandler(BaseHTTPRequestHandler):
        server_version = "StableAMD/0.3"

        def _send_json(self, status: int, payload: Any) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_bytes(self, status: int, content_type: str, payload: bytes, cache_control: str = "no-cache") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _serve_generated_image(self) -> bool:
            parsed = urlsplit(self.path)
            if self.command != "GET" or parsed.path != "/api/image":
                return False
            if resolved_repo_root is None:
                self._send_json(500, {"error": "StableAMD output root is not configured."})
                return True

            query = parse_qs(parsed.query)
            requested = query.get("path", [""])[0]
            try:
                image_path = resolve_output_image(resolved_repo_root, requested)
            except ValueError as exc:
                self._send_json(404, {"error": str(exc)})
                return True

            content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
            self._send_bytes(200, content_type, image_path.read_bytes(), cache_control="private, no-store")
            return True

        def _serve_frontend(self) -> bool:
            if static_root is None or not static_root.is_dir():
                return False

            request_path = unquote(urlsplit(self.path).path)
            relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
            candidate = (static_root / relative).resolve()
            if candidate != static_root and static_root not in candidate.parents:
                self._send_json(404, {"error": "Frontend asset not found."})
                return True
            if not candidate.is_file():
                self._send_json(404, {"error": "Frontend asset not found."})
                return True

            content_type, _ = mimetypes.guess_type(candidate.name)
            if not content_type:
                content_type = "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
                content_type += "; charset=utf-8"
            self._send_bytes(200, content_type, candidate.read_bytes())
            return True

        def _dispatch(self) -> None:
            if self._serve_generated_image():
                return

            parsed_path = urlsplit(self.path).path
            if self.command == "GET" and not parsed_path.startswith("/api/") and parsed_path != "/api":
                if self._serve_frontend():
                    return

            body = b""
            if self.command in {"POST", "PUT", "PATCH"}:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"error": "Invalid Content-Length."})
                    return
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._send_json(413, {"error": "Request body is too large."})
                    return
                body = self.rfile.read(length) if length else b""
            try:
                status, payload = api.dispatch(self.command, self.path, body)
            except StableAmdBridgeError as exc:
                status, payload = 500, {"error": str(exc)}
            except Exception as exc:
                status, payload = 500, {"error": f"StableAMD API failure: {exc}"}
            self._send_json(status, payload)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def log_message(self, format: str, *args: Any) -> None:
            return

    return StableAmdRequestHandler


def serve(repo_root: Path, host: str = "127.0.0.1", port: int = 8188) -> None:
    bind_host = validate_loopback_host(host)
    if port < 1 or port > 65535:
        raise ValueError("Port must be between 1 and 65535.")
    repo_root = Path(repo_root).resolve()
    frontend_root = repo_root / "app" / "frontend"
    index_path = frontend_root / "index.html"
    if not index_path.is_file():
        raise StableAmdBridgeError(f"StableAMD frontend index.html is missing: {index_path}")
    bridge = PowerShellBridge(repo_root)
    api = StableAmdApi(bridge)
    server = ThreadingHTTPServer((bind_host, port), make_handler(api, frontend_root, repo_root))
    print(f"StableAMD local application listening on http://{bind_host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    default_repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="StableAMD v0.3 loopback application API and web UI")
    parser.add_argument("--repo-root", default=str(default_repo_root))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args()
    serve(Path(args.repo_root), args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
