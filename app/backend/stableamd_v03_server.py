from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import stableamd_server as base


def _value(record: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return default


class PowerShellBridge(base.PowerShellBridge):
    def _post_comfy_json(self, relative_path: str, payload: dict[str, Any], timeout: int = 60) -> Any:
        url = self._backend_base_url() + relative_path.lstrip("/")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve_inpaint_model(self, request: dict[str, Any]) -> tuple[dict[str, Any], str]:
        models = [item for item in self.models() if isinstance(item, dict)]
        model_id = str(request.get("modelId") or "")
        model = next((item for item in models if str(_value(item, "id", "Id", default="")) == model_id), None)
        if model is None:
            model = next((item for item in models if str(_value(item, "family", "Family", default="")).lower() == "sdxl"), None)
        if model is None:
            raise base.StableAmdBridgeError("No registered SDXL model is available for inpainting.")
        if str(_value(model, "family", "Family", default="")).lower() != "sdxl":
            raise base.StableAmdBridgeError("StableAMD inpainting currently supports SDXL models only.")

        model_path = Path(str(_value(model, "path", "Path", default=""))).expanduser().resolve()
        if not model_path.is_file():
            raise base.StableAmdBridgeError(f"Selected model no longer exists: {model_path}")

        loader = self._comfy_json("object_info/CheckpointLoaderSimple")
        choices = self._comfy_choice_list(loader, "CheckpointLoaderSimple", "ckpt_name")
        leaf = model_path.name.lower()
        exact = [name for name in choices if Path(str(name).replace("\\", "/")).name.lower() == leaf]
        if len(exact) != 1:
            raise base.StableAmdBridgeError(
                f"ComfyUI does not expose the selected model '{model_path}'. Restart StableAMD after changing model roots."
            )
        return model, str(exact[0])

    def _resolve_inpaint_loras(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        stack = request.get("loraStack")
        if not isinstance(stack, list):
            legacy = str(request.get("loraName") or "").strip()
            stack = [] if not legacy else [
                {
                    "name": legacy,
                    "modelStrength": request.get("loraModelStrength", 1.0),
                    "clipStrength": request.get("loraClipStrength", 1.0),
                    "enabled": True,
                }
            ]
        if not stack:
            return []

        info = self._comfy_json("object_info/LoraLoader")
        choices = self._comfy_choice_list(info, "LoraLoader", "lora_name")
        by_lower = {str(name).lower(): str(name) for name in choices}
        resolved: list[dict[str, Any]] = []
        for entry in stack:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            enabled = entry.get("enabled", True) is not False
            resolved_name = name
            if enabled:
                resolved_name = by_lower.get(name.lower(), "")
                if not resolved_name:
                    raise base.StableAmdBridgeError(
                        f"ComfyUI does not expose LoRA '{name}'. Restart StableAMD after changing LoRA roots."
                    )
            resolved.append(
                {
                    "name": resolved_name or name,
                    "modelStrength": float(entry.get("modelStrength", 1.0)),
                    "clipStrength": float(entry.get("clipStrength", 1.0)),
                    "enabled": enabled,
                }
            )
        return resolved

    def _resolve_inpaint_output(self, prompt_id: str, history_entry: dict[str, Any]) -> Path:
        output_root = (self.repo_root / ".runtime" / "stableamd" / "output").resolve()
        images = history_entry.get("outputs", {}).get("9", {}).get("images", [])
        for image in images if isinstance(images, list) else []:
            if not isinstance(image, dict) or not image.get("filename"):
                continue
            candidate = (output_root / str(image.get("subfolder") or "") / str(image["filename"])).resolve()
            if output_root in candidate.parents and candidate.is_file():
                return candidate
        raise base.StableAmdBridgeError(f"ComfyUI completed inpaint prompt '{prompt_id}', but StableAMD could not resolve its output image.")

    def _save_inpaint_history(self, record: dict[str, Any]) -> Path:
        history_root = self.repo_root / ".runtime" / "stableamd" / "history"
        history_root.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc)
        prompt_id = str(record.get("promptId") or uuid.uuid4().hex)
        destination = history_root / f"{created.strftime('%Y%m%dT%H%M%S%fZ')}_{prompt_id}.json"
        temporary = destination.with_suffix(destination.suffix + f".tmp-{uuid.uuid4().hex}")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
        return destination.resolve()

    def _generate_inpaint(self, request: dict[str, Any]) -> Any:
        staged_input = base.stage_input_image(self.repo_root, request["inputImage"])
        started = time.monotonic()
        try:
            if request.get("startBackendIfNeeded"):
                try:
                    self._backend_base_url()
                except base.StableAmdBridgeError:
                    self.start_backend()

            model, checkpoint_name = self._resolve_inpaint_model(request)
            lora_stack = self._resolve_inpaint_loras(request)
            seed = int(request["seed"]) if "seed" in request else secrets.randbits(63)
            width = int(request.get("width", 1024))
            height = int(request.get("height", 1024))
            steps = int(request.get("steps", 20))
            cfg = float(request.get("cfg", 7.0))
            sampler = str(request.get("samplerName") or "euler")
            scheduler = str(request.get("scheduler") or "normal")
            denoise = float(request.get("denoise", 0.8))
            token = uuid.uuid4().hex
            filename_prefix = f"StableAMD_SDXL_INPAINT_{token}"

            workflow = self._run_script(
                "Build-StableAmdWorkflow.ps1",
                [
                    ("Family", "sdxl"),
                    ("Mode", "inpaint"),
                    ("CheckpointName", checkpoint_name),
                    ("Prompt", request["prompt"]),
                    ("NegativePrompt", request.get("negativePrompt") or "low quality, blurry, distorted, artifacts, watermark, text"),
                    ("Width", width),
                    ("Height", height),
                    ("Steps", steps),
                    ("Cfg", cfg),
                    ("Seed", seed),
                    ("SamplerName", sampler),
                    ("Scheduler", scheduler),
                    ("FilenamePrefix", filename_prefix),
                    ("InputImageName", staged_input.name),
                    ("Denoise", denoise),
                    ("LoraStackJson", json.dumps(lora_stack, ensure_ascii=False, separators=(",", ":"))),
                ],
            )
            if not isinstance(workflow, dict):
                raise base.StableAmdBridgeError("StableAMD inpaint workflow builder did not return a workflow object.")

            client_id = uuid.uuid4().hex
            queued = self._post_comfy_json("prompt", {"prompt": workflow, "client_id": client_id})
            prompt_id = str(queued.get("prompt_id") or "") if isinstance(queued, dict) else ""
            if not prompt_id:
                raise base.StableAmdBridgeError("ComfyUI /prompt did not return a prompt_id for inpainting.")
            node_errors = queued.get("node_errors") if isinstance(queued, dict) else None
            if isinstance(node_errors, dict) and node_errors:
                raise base.StableAmdBridgeError("ComfyUI rejected the StableAMD inpaint workflow: " + json.dumps(node_errors, ensure_ascii=False))

            deadline = time.monotonic() + 900
            history_entry: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                history = self._comfy_json(f"history/{prompt_id}")
                candidate = history.get(prompt_id) if isinstance(history, dict) else None
                if isinstance(candidate, dict):
                    status = candidate.get("status") or {}
                    status_str = str(status.get("status_str") or "") if isinstance(status, dict) else ""
                    if status_str == "error":
                        raise base.StableAmdBridgeError("ComfyUI reported an SDXL inpaint execution error: " + json.dumps(status, ensure_ascii=False))
                    if status_str == "success" or bool(status.get("completed")):
                        history_entry = candidate
                        break
                time.sleep(0.25)
            if history_entry is None:
                raise base.StableAmdBridgeError(f"SDXL inpainting did not complete within 900 seconds. Prompt ID: {prompt_id}")

            image_path = self._resolve_inpaint_output(prompt_id, history_entry)
            generation_seconds = round(time.monotonic() - started, 3)
            created_at = datetime.now(timezone.utc).isoformat()
            enabled_loras = [entry for entry in lora_stack if entry.get("enabled", True)]
            legacy_name = enabled_loras[0]["name"] if len(enabled_loras) == 1 else ""
            legacy_model = enabled_loras[0]["modelStrength"] if len(enabled_loras) == 1 else None
            legacy_clip = enabled_loras[0]["clipStrength"] if len(enabled_loras) == 1 else None
            model_id = str(_value(model, "id", "Id", default=""))
            model_name = str(_value(model, "name", "Name", default=Path(str(_value(model, "path", "Path", default=""))).name))
            model_path = str(Path(str(_value(model, "path", "Path", default=""))).resolve())
            record = {
                "schemaVersion": 3,
                "createdAtUtc": created_at,
                "promptId": prompt_id,
                "mode": "inpaint",
                "prompt": request["prompt"],
                "negativePrompt": request.get("negativePrompt") or "low quality, blurry, distorted, artifacts, watermark, text",
                "modelId": model_id,
                "modelName": model_name,
                "modelPath": model_path,
                "checkpointName": checkpoint_name,
                "inputImagePath": str(staged_input),
                "maskMode": "embedded-alpha",
                "denoise": denoise,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg": cfg,
                "seed": seed,
                "sampler": sampler,
                "scheduler": scheduler,
                "loraStack": lora_stack,
                "loraName": legacy_name,
                "loraModelStrength": legacy_model,
                "loraClipStrength": legacy_clip,
                "generationSeconds": generation_seconds,
                "imagePath": str(image_path),
                "backendUrl": self._backend_base_url(),
            }
            history_path = self._save_inpaint_history(record)
            return {
                "PromptId": prompt_id,
                "Mode": "inpaint",
                "Prompt": record["prompt"],
                "NegativePrompt": record["negativePrompt"],
                "ModelId": model_id,
                "ModelName": model_name,
                "ModelPath": model_path,
                "CheckpointName": checkpoint_name,
                "InputImagePath": str(staged_input),
                "MaskMode": "embedded-alpha",
                "Denoise": denoise,
                "Width": width,
                "Height": height,
                "Steps": steps,
                "Cfg": cfg,
                "Seed": seed,
                "Sampler": sampler,
                "Scheduler": scheduler,
                "LoraStack": lora_stack,
                "LoraName": legacy_name,
                "LoraModelStrength": legacy_model,
                "LoraClipStrength": legacy_clip,
                "GenerationSeconds": generation_seconds,
                "ImagePath": str(image_path),
                "HistoryPath": str(history_path),
                "BackendUrl": record["backendUrl"],
            }
        except Exception:
            try:
                staged_input.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def generate(self, request: dict[str, Any]) -> Any:
        mode = str(request.get("mode", "txt2img")).lower()
        if mode == "inpaint":
            return self._generate_inpaint(request)
        return super().generate(request)


class StableAmdApi(base.StableAmdApi):
    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        mode = request.get("mode", "txt2img")
        if mode != "inpaint":
            return super()._validate_generation(request)

        unsupported = sorted(set(request) - self._generation_fields)
        if unsupported:
            raise ValueError("Unsupported generation field(s): " + ", ".join(unsupported))

        # Reuse the proven img2img validation for prompt, image payload,
        # denoise, LoRA and numeric generation fields, then enforce the
        # inpaint-specific PNG contract used to carry the painted mask in alpha.
        proxy = dict(request)
        proxy["mode"] = "img2img"
        super()._validate_generation(proxy)

        image = request.get("inputImage")
        if not isinstance(image, dict):
            raise ValueError("inpaint requires inputImage.")
        if image.get("mimeType") != "image/png" or Path(str(image.get("name", ""))).suffix.lower() != ".png":
            raise ValueError("inpaint requires a PNG input with the mask embedded in its alpha channel.")
        return request


# The shared server creates these classes through module globals at runtime.
# Patch only the v0.3 extension points and keep the proven loopback server,
# static-file handling and lifecycle implementation untouched.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
