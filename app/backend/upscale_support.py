from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import stableamd_server as base


SUPPORTED_UPSCALE_MODEL_SUFFIXES = {".ckpt", ".pt", ".pt2", ".bin", ".pth", ".safetensors", ".pkl", ".sft"}
SUPPORTED_TARGET_FACTORS = {2, 4, 8}


def infer_upscale_scale(model_name: str) -> int | None:
    """Infer a conventional native model scale from common upscaler names."""
    name = str(model_name or "")
    for pattern in (
        r"(?i)(?:^|[_\-.])([248])x(?:[_\-.]|$)",
        r"(?i)x([248])(?:plus|[_\-.]|$)",
    ):
        match = re.search(pattern, name)
        if match:
            return int(match.group(1))
    return None


def plan_upscale_chain(
    models: list[str],
    target_factor: int,
    preferred_model: str | None = None,
) -> list[str]:
    """Return the shortest exact multiplication chain for 2x/4x/8x output."""
    try:
        target = int(target_factor)
    except (TypeError, ValueError) as exc:
        raise ValueError("Upscale factor must be 2, 4, or 8.") from exc
    if target not in SUPPORTED_TARGET_FACTORS:
        raise ValueError("Upscale factor must be 2, 4, or 8.")

    candidates: list[tuple[str, int]] = []
    for raw_name in models:
        name = str(raw_name or "").strip()
        scale = infer_upscale_scale(name)
        if name and scale in SUPPORTED_TARGET_FACTORS:
            candidates.append((name, int(scale)))
    if not candidates:
        raise ValueError(f"No installed upscale model can produce an exact {target}x result.")

    preferred = str(preferred_model or "").strip()
    if preferred:
        match = next(((name, scale) for name, scale in candidates if name.lower() == preferred.lower()), None)
        if match is None:
            raise ValueError(f"Preferred upscale model '{preferred}' is not available or its native scale is unknown.")
        name, scale = match
        product = 1
        chain: list[str] = []
        while product < target and product * scale <= target:
            product *= scale
            chain.append(name)
        if product == target:
            return chain
        raise ValueError(f"Preferred upscale model '{name}' cannot produce an exact {target}x result.")

    direct = next((name for name, scale in candidates if scale == target), None)
    if direct:
        return [direct]

    queue: deque[tuple[int, list[str]]] = deque([(1, [])])
    best_depth: dict[int, int] = {1: 0}
    while queue:
        product, chain = queue.popleft()
        for name, scale in candidates:
            next_product = product * scale
            if next_product > target or target % next_product != 0:
                continue
            next_chain = [*chain, name]
            if next_product == target:
                return next_chain
            depth = len(next_chain)
            if best_depth.get(next_product, 10**9) <= depth:
                continue
            best_depth[next_product] = depth
            queue.append((next_product, next_chain))

    raise ValueError(f"Installed upscale models cannot produce an exact {target}x result.")


def _post_json(url: str, payload: dict[str, Any], timeout: int = 60) -> Any:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class UpscalePowerShellBridge(base.PowerShellBridge):
    def _upscale_choices(self) -> list[str]:
        info = self._comfy_json("object_info/UpscaleModelLoader")

        # Legacy Comfy nodes expose enum choices directly as the first item,
        # e.g. [["model-a.pth", "model-b.pth"]]. Newer Comfy io.Schema nodes
        # expose a typed COMBO plus an options object instead:
        # ["COMBO", {"options": ["model-a.pth"]}].
        legacy = self._comfy_choice_list(info, "UpscaleModelLoader", "model_name")
        if legacy:
            return legacy

        if not isinstance(info, dict):
            return []
        node = info.get("UpscaleModelLoader")
        if not isinstance(node, dict):
            return []
        required = node.get("input", {}).get("required", {})
        spec = required.get("model_name") if isinstance(required, dict) else None
        if not isinstance(spec, list) or len(spec) < 2 or spec[0] != "COMBO" or not isinstance(spec[1], dict):
            return []
        options = spec[1].get("options")
        if not isinstance(options, list):
            return []
        return [str(value) for value in options if str(value).strip()]

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
            "modelInfo": [
                {"name": name, "nativeScale": infer_upscale_scale(name)}
                for name in models
            ],
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

    def upscale_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        factor = int(request["factor"])
        preferred = str(request.get("modelName") or "").strip() or None
        chain = plan_upscale_chain(self._upscale_choices(), factor, preferred_model=preferred)
        return {
            "factor": factor,
            "modelName": preferred or "",
            "chain": chain,
            "passes": len(chain),
            "nativeScales": [infer_upscale_scale(name) for name in chain],
        }

    def delete_history(self, prompt_id: str) -> dict[str, Any]:
        prompt_id = str(prompt_id or "").strip()
        if not prompt_id:
            raise base.StableAmdBridgeError("History prompt id is required.")

        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        if not history_root.is_dir():
            return {"deleted": False, "promptId": prompt_id, "imageDeleted": False}

        for record_path in history_root.glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or str(record.get("promptId") or "") != prompt_id:
                continue

            image_deleted = False
            raw_image = str(record.get("imagePath") or "").strip()
            if raw_image:
                try:
                    image = base.resolve_output_image(self.repo_root, raw_image)
                    image.unlink(missing_ok=True)
                    image_deleted = not image.exists()
                except (ValueError, OSError):
                    # A stale/missing image must not make the history record undeletable.
                    image_deleted = False

            try:
                record_path.unlink(missing_ok=True)
            except OSError as exc:
                raise base.StableAmdBridgeError(f"Could not delete Gallery history record: {exc}") from exc
            return {
                "deleted": True,
                "promptId": prompt_id,
                "imageDeleted": image_deleted,
            }

        return {"deleted": False, "promptId": prompt_id, "imageDeleted": False}

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

    def _run_upscale_pass(self, source: Path, model_name: str, backend_url: str) -> tuple[Path, str]:
        staged = self._stage_upscale_input(source)
        try:
            filename_prefix = f"StableAMD_UPSCALE_{uuid.uuid4().hex}"
            workflow = self._run_script(
                "Build-StableAmdUpscaleWorkflow.ps1",
                [
                    ("InputImageName", staged.name),
                    ("ModelName", model_name),
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
            return self._resolve_upscale_output(prompt_id, history_entry), prompt_id
        finally:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass

    def upscale(self, request: dict[str, Any]) -> dict[str, Any]:
        backend_url = self._backend_base_url()
        source = base.resolve_output_image(self.repo_root, str(request["imagePath"]))
        choices = self._upscale_choices()
        requested_model = str(request.get("modelName") or "").strip()
        requested_factor = request.get("factor")

        if requested_factor is None:
            exact = next((choice for choice in choices if str(choice).lower() == requested_model.lower()), None)
            if exact is None:
                raise base.StableAmdBridgeError(
                    f"ComfyUI does not expose upscale model '{requested_model}'. Put the model in StableAMD's upscale_models folder and restart the backend."
                )
            chain = [str(exact)]
            target_factor = infer_upscale_scale(str(exact))
        else:
            target_factor = int(requested_factor)
            try:
                chain = plan_upscale_chain(choices, target_factor, preferred_model=requested_model or None)
            except ValueError as exc:
                raise base.StableAmdBridgeError(str(exc)) from exc

        started = time.monotonic()
        current_source = source
        intermediate_outputs: list[Path] = []
        final_prompt_id = ""
        try:
            for index, model_name in enumerate(chain):
                output, prompt_id = self._run_upscale_pass(current_source, model_name, backend_url)
                final_prompt_id = prompt_id
                if index < len(chain) - 1:
                    intermediate_outputs.append(output)
                current_source = output

            image_path = current_source
            generation_seconds = round(time.monotonic() - started, 3)
            if len(set(chain)) == 1 and len(chain) > 1:
                chain_label = f"{chain[0]} ×{len(chain)}"
            else:
                chain_label = " → ".join(chain)
            scale_label = f"{target_factor}×" if target_factor else "native"
            record = {
                "schemaVersion": 3,
                "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "promptId": final_prompt_id or uuid.uuid4().hex,
                "mode": "upscale",
                "prompt": "Upscaled image",
                "sourceImagePath": str(source),
                "modelName": f"Upscale · {scale_label} · {chain_label}",
                "family": "upscale",
                "provider": "stock-upscale",
                "upscaleModel": chain[-1],
                "upscaleModels": chain,
                "upscalePasses": len(chain),
                "upscaleScale": target_factor,
                "generationSeconds": generation_seconds,
                "imagePath": str(image_path),
                "backendUrl": backend_url,
            }
            history_path = self._save_upscale_history(record)
            return {
                "PromptId": record["promptId"],
                "Mode": "upscale",
                "SourceImagePath": str(source),
                "ModelName": record["modelName"],
                "UpscaleModel": chain[-1],
                "UpscaleModels": chain,
                "UpscalePasses": len(chain),
                "UpscaleScale": target_factor,
                "GenerationSeconds": generation_seconds,
                "ImagePath": str(image_path),
                "HistoryPath": str(history_path),
                "BackendUrl": backend_url,
            }
        finally:
            for path in intermediate_outputs:
                if path == current_source:
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


class UpscaleStableAmdApi(base.StableAmdApi):
    _upscale_fields = {"imagePath", "modelName", "factor"}
    _upscale_plan_fields = {"modelName", "factor"}
    _history_delete_fields = {"promptId"}

    @staticmethod
    def _validate_factor(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("Upscale factor must be 2, 4, or 8.")
        try:
            factor = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Upscale factor must be 2, 4, or 8.") from exc
        if factor not in SUPPORTED_TARGET_FACTORS:
            raise ValueError("Upscale factor must be 2, 4, or 8.")
        return factor

    def _validate_upscale(self, request: dict[str, Any]) -> dict[str, Any]:
        unsupported = sorted(set(request) - self._upscale_fields)
        if unsupported:
            raise ValueError("Unsupported upscale field(s): " + ", ".join(unsupported))
        image_path = request.get("imagePath")
        if not isinstance(image_path, str) or not image_path.strip():
            raise ValueError("imagePath is required for upscale.")

        result: dict[str, Any] = {"imagePath": image_path.strip()}
        model_name = request.get("modelName")
        if model_name is not None:
            if not isinstance(model_name, str):
                raise ValueError("modelName must be a string when provided.")
            if model_name.strip():
                result["modelName"] = model_name.strip()

        if "factor" in request:
            result["factor"] = self._validate_factor(request.get("factor"))
        elif "modelName" not in result:
            raise ValueError("modelName is required when upscale factor is not provided.")
        return result

    def _validate_upscale_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        unsupported = sorted(set(request) - self._upscale_plan_fields)
        if unsupported:
            raise ValueError("Unsupported upscale plan field(s): " + ", ".join(unsupported))
        result: dict[str, Any] = {"factor": self._validate_factor(request.get("factor"))}
        model_name = request.get("modelName")
        if model_name is not None:
            if not isinstance(model_name, str):
                raise ValueError("modelName must be a string when provided.")
            if model_name.strip():
                result["modelName"] = model_name.strip()
        return result

    def _validate_history_delete(self, request: dict[str, Any]) -> str:
        unsupported = sorted(set(request) - self._history_delete_fields)
        if unsupported:
            raise ValueError("Unsupported Gallery delete field(s): " + ", ".join(unsupported))
        prompt_id = request.get("promptId")
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            raise ValueError("promptId is required to delete a Gallery item.")
        return prompt_id.strip()

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        try:
            if method == "GET" and path == "/api/upscale-models":
                return 200, self.bridge.upscale_models()
            if method == "POST" and path == "/api/upscale/plan":
                request = self._validate_upscale_plan(self._decode_json(body))
                return 200, self.bridge.upscale_plan(request)
            if method == "POST" and path == "/api/upscale":
                request = self._validate_upscale(self._decode_json(body))
                return 200, self.bridge.upscale(request)
            if method == "POST" and path == "/api/history/delete":
                prompt_id = self._validate_history_delete(self._decode_json(body))
                return 200, self.bridge.delete_history(prompt_id)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return super().dispatch(method, target, body)


# StableAMD v0.3 imports this extension before declaring its own subclasses.
# Patch the v0.3 base classes so the later model/LoRA classes inherit upscale
# support without duplicating the proven HTTP/static server implementation.
base.PowerShellBridge = UpscalePowerShellBridge
base.StableAmdApi = UpscaleStableAmdApi
