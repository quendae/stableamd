from __future__ import annotations

import base64
import gc
import importlib.util
import io
import json
import uuid
from pathlib import Path
from typing import Any

import stableamd_v03_pose_control as posecontrol

controlnet = posecontrol.controlnet
base = controlnet.base

DEPTH_ANYTHING_DEPENDENCY_ID = "depth-anything-v2-small"
DEPTH_ANYTHING_REPOSITORY = "depth-anything/Depth-Anything-V2-Small-hf"
DEPTH_ANYTHING_REVISION = "32d03942121d29edb49de4e2cc15831558af3f36"
DEPTH_ANYTHING_MODEL_FILENAME = "model.safetensors"
DEPTH_ANYTHING_MODEL_URL = (
    f"https://huggingface.co/{DEPTH_ANYTHING_REPOSITORY}/resolve/"
    f"{DEPTH_ANYTHING_REVISION}/{DEPTH_ANYTHING_MODEL_FILENAME}?download=true"
)
DEPTH_ANYTHING_MODEL_BYTES = 99_173_660
DEPTH_ANYTHING_MODEL_SHA256 = "3152477ce0d8d6978d76b995120de97cb5b928701fd0f817769f59e249a16b70"
DEPTH_ANYTHING_LICENSE = "Apache-2.0"

_DEPTH_CONFIG = {
    "_commit_hash": None,
    "architectures": ["DepthAnythingForDepthEstimation"],
    "backbone": None,
    "backbone_config": {
        "architectures": ["Dinov2Model"],
        "hidden_size": 384,
        "image_size": 518,
        "model_type": "dinov2",
        "num_attention_heads": 6,
        "out_features": ["stage3", "stage6", "stage9", "stage12"],
        "out_indices": [3, 6, 9, 12],
        "patch_size": 14,
        "reshape_hidden_states": False,
        "torch_dtype": "float32",
    },
    "fusion_hidden_size": 64,
    "head_hidden_size": 32,
    "head_in_index": -1,
    "initializer_range": 0.02,
    "model_type": "depth_anything",
    "neck_hidden_sizes": [48, 96, 192, 384],
    "patch_size": 14,
    "reassemble_factors": [4, 2, 1, 0.5],
    "reassemble_hidden_size": 384,
    "torch_dtype": "float32",
    "transformers_version": None,
    "use_pretrained_backbone": False,
}

_DEPTH_PREPROCESSOR_CONFIG = {
    "_valid_processor_keys": [
        "images",
        "do_resize",
        "size",
        "keep_aspect_ratio",
        "ensure_multiple_of",
        "resample",
        "do_rescale",
        "rescale_factor",
        "do_normalize",
        "image_mean",
        "image_std",
        "do_pad",
        "size_divisor",
        "return_tensors",
        "data_format",
        "input_data_format",
    ],
    "do_normalize": True,
    "do_pad": False,
    "do_rescale": True,
    "do_resize": True,
    "ensure_multiple_of": 14,
    "image_mean": [0.485, 0.456, 0.406],
    "image_processor_type": "DPTImageProcessor",
    "image_std": [0.229, 0.224, 0.225],
    "keep_aspect_ratio": True,
    "resample": 3,
    "rescale_factor": 0.00392156862745098,
    "size": {"height": 518, "width": 518},
    "size_divisor": None,
}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class DepthControlBridgeMixin:
    """Adds a managed Depth Anything V2 Small preprocessor and Z-Image Depth control.

    Depth inference runs on CPU so installing or previewing a depth map does not
    disturb the accepted ComfyUI/Radeon working set. Z-Image then consumes the
    prepared grayscale map through the already accepted Union 2.1 Lite route.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        self._stableamd_depth_runtime: tuple[Any, Any] | None = None

    def _depth_model_root(self) -> Path:
        return (
            self.repo_root
            / ".runtime"
            / "stableamd"
            / "models"
            / "preprocessors"
            / "depth-anything-v2-small-hf"
        ).resolve()

    def _depth_model_path(self) -> Path:
        return self._depth_model_root() / DEPTH_ANYTHING_MODEL_FILENAME

    def _depth_python_ready(self) -> bool:
        return all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers", "PIL"))

    def _depth_model_on_disk(self) -> bool:
        path = self._depth_model_path()
        return path.is_file() and path.stat().st_size == DEPTH_ANYTHING_MODEL_BYTES

    def _depth_preprocessor_ready(self) -> bool:
        root = self._depth_model_root()
        return (
            self._depth_model_on_disk()
            and (root / "config.json").is_file()
            and (root / "preprocessor_config.json").is_file()
            and self._depth_python_ready()
        )

    def _zimage_depth_ready(self) -> bool:
        patch_resolver = getattr(self, "_zimage_fun_patch_name", None)
        patch_ready = bool(callable(patch_resolver) and patch_resolver(required=False))
        return self._depth_preprocessor_ready() and patch_ready and all(
            self._node_available(name) for name in ("ModelPatchLoader", "ZImageFunControlnet")
        )

    def controlnet_dependencies(self) -> dict[str, Any]:
        payload = super().controlnet_dependencies()
        dependencies = payload.setdefault("dependencies", [])
        model_path = self._depth_model_path()
        model_size_ok = model_path.is_file() and model_path.stat().st_size == DEPTH_ANYTHING_MODEL_BYTES
        dependencies.append(
            {
                "id": DEPTH_ANYTHING_DEPENDENCY_ID,
                "name": "Depth Anything V2 Small",
                "family": "shared-preprocessor",
                "type": "depth-preprocessor",
                "ready": self._depth_preprocessor_ready(),
                "installable": True,
                "restartRequired": False,
                "repository": DEPTH_ANYTHING_REPOSITORY,
                "revision": DEPTH_ANYTHING_REVISION,
                "model": {
                    "filename": DEPTH_ANYTHING_MODEL_FILENAME,
                    "sizeBytes": DEPTH_ANYTHING_MODEL_BYTES,
                    "sha256": DEPTH_ANYTHING_MODEL_SHA256,
                    "license": DEPTH_ANYTHING_LICENSE,
                    "installedOnDisk": model_path.is_file(),
                    "integrity": "size-ok" if model_size_ok else ("size-mismatch" if model_path.is_file() else "missing"),
                },
                "note": "Runs locally on CPU and converts a normal image into a grayscale depth map before Control guidance.",
            }
        )
        return payload

    def install_controlnet_dependency(self, dependency_id: str) -> dict[str, Any]:
        dependency_id = str(dependency_id or "").strip()
        if dependency_id != DEPTH_ANYTHING_DEPENDENCY_ID:
            return super().install_controlnet_dependency(dependency_id)

        root = self._depth_model_root()
        root.mkdir(parents=True, exist_ok=True)
        model_path = self._depth_model_path()
        changed = controlnet._download_pinned(
            DEPTH_ANYTHING_MODEL_URL,
            model_path,
            DEPTH_ANYTHING_MODEL_BYTES,
            DEPTH_ANYTHING_MODEL_SHA256,
        )
        _atomic_json(root / "config.json", _DEPTH_CONFIG)
        _atomic_json(root / "preprocessor_config.json", _DEPTH_PREPROCESSOR_CONFIG)
        self._stableamd_depth_runtime = None
        ready = self._depth_preprocessor_ready()
        return {
            "id": DEPTH_ANYTHING_DEPENDENCY_ID,
            "installed": True,
            "modelPath": str(model_path),
            "modelChanged": changed,
            "ready": ready,
            "restartRequired": False,
            "repository": DEPTH_ANYTHING_REPOSITORY,
            "revision": DEPTH_ANYTHING_REVISION,
            "modelSha256": DEPTH_ANYTHING_MODEL_SHA256,
            "license": DEPTH_ANYTHING_LICENSE,
            "runtimeReady": self._depth_python_ready(),
        }

    def model_support(self) -> dict[str, Any]:
        support = super().model_support()
        if not isinstance(support, dict):
            return support
        ready = self._zimage_depth_ready()
        for entry in support.get("models", []):
            if not isinstance(entry, dict) or str(entry.get("family") or "").lower() != "z-image-turbo":
                continue
            policy = entry.setdefault("controlPolicy", {})
            controls = policy.setdefault("controls", [])
            if not any(str(item.get("id") or "").lower() == "depth" for item in controls if isinstance(item, dict)):
                controls.append(
                    {
                        "id": "depth",
                        "label": "Depth",
                        "status": "supported" if ready else "planned",
                        "inputKind": "source-image",
                        "preprocessor": DEPTH_ANYTHING_DEPENDENCY_ID,
                        "strengthDefault": 1.0,
                        "dependencyId": DEPTH_ANYTHING_DEPENDENCY_ID,
                        "installable": True,
                    }
                )
            policy["note"] = (
                "Union 2.1 exposes Canny, OpenPose and Depth. Depth uses the managed "
                "Depth Anything V2 Small preprocessor; OpenPose accepts templates/editor maps."
            )
        return support

    def _load_depth_runtime(self) -> tuple[Any, Any]:
        if not self._depth_preprocessor_ready():
            raise base.StableAmdBridgeError(
                "Depth control requires the managed Depth Anything V2 Small dependency. "
                "Install it from Control guidance first."
            )
        if self._stableamd_depth_runtime is not None:
            return self._stableamd_depth_runtime
        try:
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        except Exception as exc:
            raise base.StableAmdBridgeError(
                "Depth Anything V2 requires the transformers package from the managed StableAMD runtime."
            ) from exc

        root = self._depth_model_root()
        try:
            processor = AutoImageProcessor.from_pretrained(root, local_files_only=True, trust_remote_code=False)
            model = AutoModelForDepthEstimation.from_pretrained(root, local_files_only=True, trust_remote_code=False)
            model.eval()
            model.to("cpu")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Depth Anything V2 Small could not be loaded: {exc}") from exc
        self._stableamd_depth_runtime = (processor, model)
        return self._stableamd_depth_runtime

    def preprocess_depth(self, image_payload: Any) -> dict[str, Any]:
        try:
            from PIL import Image
            import torch
            import torch.nn.functional as torch_functional
        except Exception as exc:
            raise base.StableAmdBridgeError(
                "Depth preprocessing requires Pillow and PyTorch from the managed StableAMD runtime."
            ) from exc

        _, image_bytes = base._decode_input_image(image_payload)
        try:
            source = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Depth source image could not be decoded: {exc}") from exc

        processor, model = self._load_depth_runtime()
        width, height = source.size
        try:
            inputs = processor(images=source, return_tensors="pt")
            inputs = {key: value.to("cpu") for key, value in inputs.items()}
            with torch.inference_mode():
                predicted = model(**inputs).predicted_depth
                predicted = torch_functional.interpolate(
                    predicted.unsqueeze(1),
                    size=(height, width),
                    mode="bicubic",
                    align_corners=False,
                ).squeeze(1)
                minimum = predicted.amin(dim=(1, 2), keepdim=True)
                maximum = predicted.amax(dim=(1, 2), keepdim=True)
                normalized = (predicted - minimum) / (maximum - minimum).clamp_min(1e-6)
                pixels = normalized[0].mul(255.0).round().clamp(0, 255).to(torch.uint8).cpu().numpy()
            depth_image = Image.fromarray(pixels).convert("RGB")
            output = io.BytesIO()
            depth_image.save(output, format="PNG", optimize=True)
        except Exception as exc:
            raise base.StableAmdBridgeError(f"Depth preprocessing failed: {exc}") from exc
        finally:
            gc.collect()

        original_name = "source"
        if isinstance(image_payload, dict):
            original_name = Path(str(image_payload.get("name") or "source")).stem or "source"
        result_image = {
            "name": f"{original_name}-depth.png",
            "mimeType": "image/png",
            "dataBase64": base64.b64encode(output.getvalue()).decode("ascii"),
        }
        return {
            "image": result_image,
            "width": width,
            "height": height,
            "preprocessor": DEPTH_ANYTHING_DEPENDENCY_ID,
        }

    def _inject_zimage_depth(self, workflow: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        for node_id in ("11", "29", "3"):
            if not isinstance(workflow.get(node_id), dict):
                raise base.StableAmdBridgeError("Z-Image workflow anchors are missing for Depth control.")
        sampler_model = workflow["11"].get("inputs", {}).get("model")
        if not isinstance(sampler_model, list):
            raise base.StableAmdBridgeError("Z-Image sampling model input is missing for Depth control.")

        patch_name = self._zimage_fun_patch_name(required=True)
        width = int(context["width"])
        height = int(context["height"])
        workflow["80"] = {"class_type": "LoadImage", "inputs": {"image": context["image_name"]}}
        workflow["81"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["80", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "center",
            },
        }
        workflow["82"] = {"class_type": "ModelPatchLoader", "inputs": {"name": str(patch_name)}}
        workflow["83"] = {
            "class_type": "ZImageFunControlnet",
            "inputs": {
                "model": sampler_model,
                "model_patch": ["82", 0],
                "vae": ["29", 0],
                "strength": float(context["strength"]),
                "image": ["81", 0],
            },
        }
        workflow["11"]["inputs"]["model"] = ["83", 0]
        return workflow

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        result = super()._run_script(name, parameters)
        context = self._active_control_context()
        if name != "Build-StableAmdWorkflow.ps1" or not context or not isinstance(result, dict):
            return result
        if str(context.get("family") or "") == "z-image-turbo" and str(context.get("type") or "") == "depth":
            return self._inject_zimage_depth(result, context)
        return result

    def _generate_zimage_depth(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        control: dict[str, Any],
    ) -> Any:
        if not self._zimage_depth_ready():
            raise base.StableAmdBridgeError(
                "Z-Image Depth requires the accepted Union 2.1 Lite route and the managed Depth Anything V2 Small preprocessor."
            )
        if request.get("loraStack") or str(request.get("loraName") or "").strip():
            raise base.StableAmdBridgeError("Disable regular LoRAs for the first Z-Image Depth acceptance gate.")

        staged = base.stage_input_image(self.repo_root, control["image"])
        strength = self._number(control.get("strength"), 1.0, 0.0, 2.0, "Control strength")
        context = {
            "family": "z-image-turbo",
            "type": "depth",
            "image_name": staged.name,
            "width": int(request.get("width", 1024)),
            "height": int(request.get("height", 1024)),
            "strength": strength,
        }
        clean = dict(request)
        clean.pop("control", None)
        self._stableamd_control_context.value = context
        try:
            result = super()._generate_zimage_turbo(clean, model)
        finally:
            self._stableamd_control_context.value = None
            staged.unlink(missing_ok=True)

        metadata = {
            "type": "depth",
            "inputKind": "depth-anything-v2-small-map",
            "inputName": str(control.get("image", {}).get("name") or "depth-map"),
            "strength": strength,
            "provider": "z-image-fun-control-union-2.1",
            "preprocessor": DEPTH_ANYTHING_DEPENDENCY_ID,
        }
        result["Mode"] = "controlnet"
        result["Control"] = metadata
        self._persist_control_metadata(result, metadata)
        return result

    def generate(self, request: dict[str, Any]) -> Any:
        control = self._control_request(request)
        if control is None:
            return super().generate(request)
        selected = self._selected_product_model(request)
        family = ""
        if isinstance(selected, dict):
            family = str(selected.get("family") or selected.get("Family") or "").lower()
        control_type = str(control.get("type") or "").lower()
        if family == "z-image-turbo" and control_type == "depth":
            if str(request.get("mode") or "txt2img").lower() != "txt2img":
                raise base.StableAmdBridgeError("Depth control currently starts from txt2img mode only.")
            return self._generate_zimage_depth(request, selected, control)
        return super().generate(request)


class DepthControlApiMixin:
    """Adds local depth preprocessing while reusing the existing ControlNet request contract."""

    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        control = request.get("control")
        if isinstance(control, dict) and str(control.get("type") or "").lower() == "depth":
            adjusted = dict(request)
            adjusted_control = dict(control)
            adjusted_control["type"] = "openpose"
            adjusted["control"] = adjusted_control
            validated = super()._validate_generation(adjusted)
            if isinstance(validated, dict):
                validated["control"] = dict(control)
            return validated
        return super()._validate_generation(request)

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        if method == "POST" and path == "/api/controlnet/preprocess/depth":
            try:
                request = self._decode_json(body)
                unsupported = sorted(set(request) - {"image"})
                if unsupported:
                    raise ValueError("Unsupported Depth preprocess field(s): " + ", ".join(unsupported))
                if "image" not in request:
                    raise ValueError("Depth preprocessing requires image.")
                base._decode_input_image(request["image"])
                return 200, self.bridge.preprocess_depth(request["image"])
            except ValueError as exc:
                return 400, {"error": str(exc)}
            except base.StableAmdBridgeError as exc:
                return 409, {"error": str(exc)}
        return super().dispatch(method, target, body)
