from __future__ import annotations

import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import stableamd_server as base


SUPPORTED_UPSCALE_MODEL_SUFFIXES = {".ckpt", ".pt", ".pt2", ".bin", ".pth", ".safetensors", ".pkl", ".sft"}


def _post_json(url: str, payload: dict[str, Any], timeout: int = 60) -> Any:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class UpscalePowerShellBridge(base.PowerShellBridge):
    def _upscale_choices(self) -> list[str]:
        info = self._comfy_json("object_info/UpscaleModelLoader")
        return self._comfy_choice_list(info, "UpscaleModelLoader", "model_name")

    def upscale_models(self) -> dict[str, Any]:
        root = (self.repo_root / ".runtime" / "stableamd" / "models" / "upscale_models").resolve()
        models = [str(item) for item in self._upscale_choices() if str(item).strip()]
        disk_models: list[str] = []
        if root.is_dir():
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_UPSCALE_MODEL_SUFFIXES:
                    continue
                disk_models.append(path.relative_to(root).as_posix())
        disk_models.sort(key=str.lower)

        registered = {str(item).replace("\\", "/").lower() for item in models}
        unregistered = [item for item in disk_models if item.lower() not in registered]
        return {
            "root": str(root),
            "models": models,
            "diskModels": disk_models,
            "unregisteredModels": unregistered,
            "restartRecommended": bool(unregistered),
            "recommendations": [
                {
                    "name": "4x-UltraSharp",
                    "purpose": "General sharp 4x upscale",
                    "status": "install-model-file",
                },
                {
                    "name": "RealESRGAN x4plus",
                    "purpose": "General/photo 4x upscale",
                    "status": "install-model-file",
                },
                {
                    "name": "RealESRGAN x2plus",
                    "purpose": "Faster/lighter 2x upscale",
                    "status": "install-model-file",
                },
            ],
        }

    def _stage_upscale_input(self, source: Path) -> Path:
        input_root = (self.repo_root / ".runtime" / "stableamd" / "input").resolve()
        input_root.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise base.StableAmdBridgeError("Upscale source must be PNG, JPEG, or WebP.")
        destination = (input_root / f"upscale_{uuid.uuid4().hex}{suffix}").resolve()
        if input_root not in destination.parents:
            raise base.StableAmdBridgeError("Could not stage upscale input safely.")
        shutil.copy2(source, destination)
        return destination

    def _resolve_upscale_output(self, prompt_id: str, history_entry: dict[str, Any]) -> Path:
        output_root = (self.repo_root / ".runtime" / "stableamd" / "output").resolve()
        images = history_entry.get("outputs", {}).get("9", {}).get("images", [])
        for image in images if isinstance(images, list) else []:
            if not isinstance(image, dict) or not image.get("filename"):
                continue
            candidate = (output_root / str(image.get("subfolder") or "") / str(image["filename"])).resolve()
            if output_root in candidate.parents and candidate.is_file():
                return candidate
        raise base.StableAmdBridgeError(
            f"ComfyUI completed upscale prompt '{prompt_id}', but StableAMD could not resolve its output image."
        )

    def _save_upscale_history(self, record: dict[str, Any]) -> Path:
        history_root = self.repo_root / ".runtime" / "stableamd" / "history"
        history_root.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc)
        prompt_id = str(record.get("promptId") or uuid.uuid4().hex)
        destination = history_root / f"{created.strftime('%Y%m%dT%H%M%S%fZ')}_{prompt_id}.json"
        temporary = destination.with_suffix(destination.suffix + f".tmp-{uuid.uuid4().hex}")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
        return destination.resolve()

    def upscale(self, request: dict[str, Any]) -> dict[str, Any]:
        backend_url = self._backend_base_url()
        source = base.resolve_output_image(self.repo_root, str(request["imagePath"]))
        requested_model = str(request["modelName"]).strip()
        choices = self._upscale_choices()
        exact = next((choice for choice in choices if str(choice).lower() == requested_model.lower()), None)
        if exact is None:
            raise base.StableAmdBridgeError(
                f"ComfyUI does not expose upscale model '{requested_model}'. Put the model in StableAMD's upscale_models folder and restart the backend."
            )

        staged = self._stage_upscale_input(source)
        started = time.monotonic()
        try:
            filename_prefix = f"StableAMD_UPSCALE_{uuid.uuid4().hex}"
            workflow = self._run_script(
                "Build-StableAmdUpscaleWorkflow.ps1",
                [
                    ("InputImageName", staged.name),
                    ("ModelName", str(exact)),
                    ("FilenamePrefix", filename_prefix),
                ],
            )
            if not isinstance(workflow, dict):
                raise base.StableAmdBridgeError("StableAMD upscale workflow builder did not return a workflow object.")

            queued = _post_json(
                backend_url + "prompt",
                {"prompt": workflow, "client_id": uuid.uuid4().hex},
            )
            prompt_id = str(queued.get("prompt_id") or "") if isinstance(queued, dict) else ""
            if not prompt_id:
                raise base.StableAmdBridgeError("ComfyUI /prompt did not return a prompt_id for upscaling.")
            node_errors = queued.get("node_errors") if isinstance(queued, dict) else None
            if isinstance(node_errors, dict) and node_errors:
                raise base.StableAmdBridgeError(
                    "ComfyUI rejected the StableAMD upscale workflow: " + json.dumps(node_errors, ensure_ascii=False)
                )

            deadline = time.monotonic() + 900
            history_entry: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                history = self._comfy_json(f"history/{prompt_id}")
                candidate = history.get(prompt_id) if isinstance(history, dict) else None
                if isinstance(candidate, dict):
                    status = candidate.get("status") or {}
                    status_str = str(status.get("status_str") or "") if isinstance(status, dict) else ""
                    if status_str == "error":
                        raise base.StableAmdBridgeError(
                            "ComfyUI reported an upscale execution error: " + json.dumps(status, ensure_ascii=False)
                        )
                    if status_str == "success" or bool(status.get("completed")):
                        history_entry = candidate
                        break
                time.sleep(0.25)
            if history_entry is None:
                raise base.StableAmdBridgeError(f"Upscaling did not complete within 900 seconds. Prompt ID: {prompt_id}")

            image_path = self._resolve_upscale_output(prompt_id, history_entry)
            generation_seconds = round(time.monotonic() - started, 3)
            record = {
                "schemaVersion": 3,
                "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "promptId": prompt_id,
                "mode": "upscale",
                "prompt": "",
                "sourceImagePath": str(source),
                "upscaleModel": str(exact),
                "generationSeconds": generation_seconds,
                "imagePath": str(image_path),
                "backendUrl": backend_url,
            }
            history_path = self._save_upscale_history(record)
            return {
                "PromptId": prompt_id,
                "Mode": "upscale",
                "SourceImagePath": str(source),
                "UpscaleModel": str(exact),
                "GenerationSeconds": generation_seconds,
                "ImagePath": str(image_path),
                "HistoryPath": str(history_path),
                "BackendUrl": backend_url,
            }
        finally:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass


class UpscaleStableAmdApi(base.StableAmdApi):
    _upscale_fields = {"imagePath", "modelName"}

    def _validate_upscale(self, request: dict[str, Any]) -> dict[str, Any]:
        unsupported = sorted(set(request) - self._upscale_fields)
        if unsupported:
            raise ValueError("Unsupported upscale field(s): " + ", ".join(unsupported))
        image_path = request.get("imagePath")
        model_name = request.get("modelName")
        if not isinstance(image_path, str) or not image_path.strip():
            raise ValueError("imagePath is required for upscale.")
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("modelName is required for upscale.")
        return {"imagePath": image_path.strip(), "modelName": model_name.strip()}

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        try:
            if method == "GET" and path == "/api/upscale-models":
                return 200, self.bridge.upscale_models()
            if method == "POST" and path == "/api/upscale":
                request = self._validate_upscale(self._decode_json(body))
                return 200, self.bridge.upscale(request)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return super().dispatch(method, target, body)


# StableAMD v0.3 imports this extension before declaring its own subclasses.
# Patch the v0.3 base classes so the later model/LoRA classes inherit upscale
# support without duplicating the proven HTTP/static server implementation.
base.PowerShellBridge = UpscalePowerShellBridge
base.StableAmdApi = UpscaleStableAmdApi
