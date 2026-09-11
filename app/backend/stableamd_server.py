from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

SERVICE_NAME = "StableAMD"
API_VERSION = 1
MAX_REQUEST_BYTES = 1024 * 1024


class StableAmdBridgeError(RuntimeError):
    pass


def validate_loopback_host(host: str) -> str:
    normalized = (host or "").strip().lower()
    if normalized in {"127.0.0.1", "localhost"}:
        return "127.0.0.1"
    if normalized == "::1":
        return "::1"
    raise ValueError("StableAMD v0.1 may bind only to a loopback host.")


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

    def models(self) -> Any:
        result = self._run_script("List-Models.ps1")
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    def history(self, limit: int = 0) -> Any:
        parameters: list[tuple[str, Any]] = []
        if limit > 0:
            parameters.append(("Limit", limit))
        result = self._run_script("Get-GenerationHistory.ps1", parameters)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

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
            "startBackendIfNeeded": "StartBackendIfNeeded",
        }
        for source, target in mapping.items():
            if source in request:
                parameters.append((target, request[source]))
        return self._run_script("Invoke-Txt2Img.ps1", parameters)

    def start_backend(self) -> Any:
        return self._run_script("Start-StableAMD.ps1")

    def stop_backend(self) -> Any:
        return self._run_script("Stop-StableAMD.ps1")

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
        "startBackendIfNeeded",
    }

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
            if method == "GET" and path == "/api/models":
                return 200, self.bridge.models()
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
            if method == "POST" and path == "/api/backend/stop":
                self._decode_json(body)
                return 200, self.bridge.stop_backend()
            if method == "POST" and path == "/api/generate":
                request = self._decode_json(body)
                unsupported = sorted(set(request) - self._generation_fields)
                if unsupported:
                    return 400, {"error": "Unsupported generation field(s): " + ", ".join(unsupported)}
                prompt = request.get("prompt")
                if not isinstance(prompt, str) or not prompt.strip():
                    return 400, {"error": "Generation prompt must be a non-empty string."}
                return 200, self.bridge.generate(request)
        except ValueError as exc:
            return 400, {"error": str(exc)}

        return 404, {"error": "API route not found."}


def make_handler(api: StableAmdApi):
    class StableAmdRequestHandler(BaseHTTPRequestHandler):
        server_version = "StableAMD/0.1"

        def _send(self, status: int, payload: Any) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _dispatch(self) -> None:
            body = b""
            if self.command in {"POST", "PUT", "PATCH"}:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send(400, {"error": "Invalid Content-Length."})
                    return
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._send(413, {"error": "Request body is too large."})
                    return
                body = self.rfile.read(length) if length else b""
            try:
                status, payload = api.dispatch(self.command, self.path, body)
            except StableAmdBridgeError as exc:
                status, payload = 500, {"error": str(exc)}
            except Exception as exc:  # Keep the local server alive and return a product-level error.
                status, payload = 500, {"error": f"StableAMD API failure: {exc}"}
            self._send(status, payload)

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
    bridge = PowerShellBridge(Path(repo_root))
    api = StableAmdApi(bridge)
    server = ThreadingHTTPServer((bind_host, port), make_handler(api))
    print(f"StableAMD local API listening on http://{bind_host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    default_repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="StableAMD v0.1 loopback application API")
    parser.add_argument("--repo-root", default=str(default_repo_root))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args()
    serve(Path(args.repo_root), args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
