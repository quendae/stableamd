from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import uuid
from pathlib import Path
from threading import local
from typing import Any
from urllib.request import Request, urlopen

import stableamd_v03_edit_server_base as editing

base = editing.base

KREA_OPENPOSE_PLUGIN_REPO = "https://github.com/ostris/ComfyUI-Krea2-Ostris-Edit.git"
KREA_OPENPOSE_PLUGIN_COMMIT = "7756566160c4a1b24bb1bd9f0ff3ced1a83d7547"
KREA_OPENPOSE_LORA = "krea2_turbo_openpose_controlnet.safetensors"
KREA_OPENPOSE_LORA_URL = (
    "https://huggingface.co/thedeoxen/Krea-2-pose-controlnet/resolve/main/"
    "krea2_turbo_openpose_controlnet.safetensors?download=true"
)
KREA_OPENPOSE_LORA_BYTES = 228_587_504
KREA_OPENPOSE_LORA_SHA256 = "0ddc3aafce4abdf7af3309b2f00c1bacdf15df1f2b4fb7adc9ff71795da90ecf"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_pinned(url: str, destination: Path, expected_bytes: int, expected_sha256: str) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if destination.stat().st_size != expected_bytes or _sha256_file(destination) != expected_sha256:
            raise base.StableAmdBridgeError(
                f"A different or corrupt file already exists at '{destination}'. Remove or rename it before installing."
            )
        return False

    temporary = destination.with_name(f".{destination.name}.partial-{uuid.uuid4().hex}")
    digest = hashlib.sha256()
    total = 0
    request = Request(url, headers={"User-Agent": "StableAMD/0.3 controlnet-installer"}, method="GET")
    try:
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_bytes:
                    raise base.StableAmdBridgeError("Control dependency download exceeded its pinned expected size.")
                digest.update(chunk)
                output.write(chunk)
        if total != expected_bytes:
            raise base.StableAmdBridgeError(
                f"Control dependency size mismatch: expected {expected_bytes} bytes, received {total}."
            )
        if digest.hexdigest() != expected_sha256:
            raise base.StableAmdBridgeError("Control dependency checksum mismatch. The downloaded file was not installed.")
        temporary.replace(destination)
        return True
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class ControlNetBridgeMixin:
    """Provider-aware ControlNet layer for Z-Image Turbo and Krea 2 Turbo.

    The first target gates deliberately use concrete, proven provider routes:
    Z-Image uses the already accepted Union 2.1 Lite patch + core Canny node;
    Krea 2 uses an MIT reference-conditioning plugin plus the Apache-2.0 Turbo
    OpenPose adapter. Other control types remain gated until their own target
    graphs are pinned and accepted.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        self._stableamd_control_context = local()

    def _active_control_context(self) -> dict[str, Any] | None:
        value = getattr(self._stableamd_control_context, "value", None)
        return value if isinstance(value, dict) else None

    def _node_available(self, node_name: str) -> bool:
        try:
            payload = self._comfy_json(f"object_info/{node_name}")
        except base.StableAmdBridgeError:
            return False
        return isinstance(payload, dict) and isinstance(payload.get(node_name), dict)

    def _lora_choice_by_leaf(self, filename: str, node_name: str = "LoraLoaderModelOnly") -> str | None:
        try:
            payload = self._comfy_json(f"object_info/{node_name}")
        except base.StableAmdBridgeError:
            return None
        choices = self._combo_choices(payload, node_name, "lora_name")
        leaf = filename.lower()
        matches = [
            str(value)
            for value in choices
            if Path(str(value).replace("\\", "/")).name.lower() == leaf
        ]
        return matches[0] if len(matches) == 1 else None

    def _zimage_canny_ready(self) -> bool:
        patch_resolver = getattr(self, "_zimage_fun_patch_name", None)
        patch_ready = bool(callable(patch_resolver) and patch_resolver(required=False))
        return patch_ready and all(
            self._node_available(name)
            for name in ("Canny", "ModelPatchLoader", "ZImageFunControlnet")
        )

    def _krea_openpose_ready(self) -> bool:
        nodes_ready = all(
            self._node_available(name)
            for name in ("TextEncodeKrea2OstrisEdit", "Krea2OstrisEditModelPatch", "LoraLoaderModelOnly")
        )
        return nodes_ready and self._lora_choice_by_leaf(KREA_OPENPOSE_LORA) is not None

    def controlnet_dependencies(self) -> dict[str, Any]:
        plugin_root = (
            self.repo_root
            / ".runtime"
            / "therock-comfy"
            / "ComfyUI"
            / "custom_nodes"
            / "ComfyUI-Krea2-Ostris-Edit"
        ).resolve()
        lora_path = (
            self.repo_root
            / ".runtime"
            / "stableamd"
            / "models"
            / "loras"
            / "krea"
            / KREA_OPENPOSE_LORA
        ).resolve()
        lora_size_ok = lora_path.is_file() and lora_path.stat().st_size == KREA_OPENPOSE_LORA_BYTES
        return {
            "dependencies": [
                {
                    "id": "zimage-canny",
                    "name": "Z-Image Canny / Union 2.1",
                    "family": "z-image-turbo",
                    "type": "canny",
                    "ready": self._zimage_canny_ready(),
                    "installable": False,
                    "note": "Uses the existing curated Union 2.1 Lite patch and the pinned ComfyUI Canny node.",
                },
                {
                    "id": "krea2-openpose",
                    "name": "Krea 2 Turbo OpenPose control",
                    "family": "krea2",
                    "type": "openpose",
                    "ready": self._krea_openpose_ready(),
                    "installable": True,
                    "restartRequired": bool((plugin_root.exists() or lora_size_ok) and not self._krea_openpose_ready()),
                    "plugin": {
                        "repository": KREA_OPENPOSE_PLUGIN_REPO,
                        "commit": KREA_OPENPOSE_PLUGIN_COMMIT,
                        "license": "MIT",
                        "installedOnDisk": plugin_root.is_dir(),
                    },
                    "model": {
                        "filename": KREA_OPENPOSE_LORA,
                        "sizeBytes": KREA_OPENPOSE_LORA_BYTES,
                        "sha256": KREA_OPENPOSE_LORA_SHA256,
                        "license": "Apache-2.0",
                        "installedOnDisk": lora_path.is_file(),
                        "integrity": "size-ok" if lora_size_ok else ("size-mismatch" if lora_path.is_file() else "missing"),
                    },
                    "note": "First gate accepts a prepared OpenPose/DWPose skeleton map; automatic pose extraction follows later.",
                },
            ]
        }

    def install_controlnet_dependency(self, dependency_id: str) -> dict[str, Any]:
        if str(dependency_id or "").strip() != "krea2-openpose":
            raise base.StableAmdBridgeError(f"Unknown ControlNet dependency id '{dependency_id}'.")

        git = shutil.which("git.exe") or shutil.which("git")
        if not git:
            raise base.StableAmdBridgeError("Git is required to install the pinned Krea 2 OpenPose ComfyUI integration.")

        comfy_root = (self.repo_root / ".runtime" / "therock-comfy" / "ComfyUI").resolve()
        custom_nodes = comfy_root / "custom_nodes"
        custom_nodes.mkdir(parents=True, exist_ok=True)
        plugin_root = custom_nodes / "ComfyUI-Krea2-Ostris-Edit"
        plugin_changed = False

        if plugin_root.exists():
            if not (plugin_root / ".git").is_dir():
                raise base.StableAmdBridgeError(
                    f"'{plugin_root}' already exists but is not a Git checkout. Move it aside before managed installation."
                )
            head = subprocess.run(
                [git, "-C", str(plugin_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if head.returncode != 0 or head.stdout.strip().lower() != KREA_OPENPOSE_PLUGIN_COMMIT.lower():
                raise base.StableAmdBridgeError(
                    "Krea 2 OpenPose plugin already exists at a different revision. StableAMD will not overwrite an unmanaged checkout."
                )
        else:
            temporary = custom_nodes / f".stableamd-krea2-openpose-{uuid.uuid4().hex}"
            try:
                clone = subprocess.run(
                    [git, "clone", "--filter=blob:none", "--no-checkout", KREA_OPENPOSE_PLUGIN_REPO, str(temporary)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                )
                if clone.returncode != 0:
                    raise base.StableAmdBridgeError((clone.stderr or clone.stdout or "git clone failed").strip())
                checkout = subprocess.run(
                    [git, "-C", str(temporary), "checkout", "--detach", KREA_OPENPOSE_PLUGIN_COMMIT],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                if checkout.returncode != 0:
                    raise base.StableAmdBridgeError((checkout.stderr or checkout.stdout or "git checkout failed").strip())
                temporary.replace(plugin_root)
                plugin_changed = True
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

        lora_path = (
            self.repo_root
            / ".runtime"
            / "stableamd"
            / "models"
            / "loras"
            / "krea"
            / KREA_OPENPOSE_LORA
        ).resolve()
        lora_changed = _download_pinned(
            KREA_OPENPOSE_LORA_URL,
            lora_path,
            KREA_OPENPOSE_LORA_BYTES,
            KREA_OPENPOSE_LORA_SHA256,
        )
        ready = self._krea_openpose_ready()
        return {
            "id": "krea2-openpose",
            "installed": True,
            "pluginInstalled": plugin_root.is_dir(),
            "pluginChanged": plugin_changed,
            "modelPath": str(lora_path),
            "modelChanged": lora_changed,
            "ready": ready,
            "restartRequired": not ready or plugin_changed or lora_changed,
            "pluginCommit": KREA_OPENPOSE_PLUGIN_COMMIT,
            "modelSha256": KREA_OPENPOSE_LORA_SHA256,
        }

    def model_support(self) -> dict[str, Any]:
        support = super().model_support()
        if not isinstance(support, dict):
            return support

        z_ready = self._zimage_canny_ready()
        k_ready = self._krea_openpose_ready()
        for entry in support.get("models", []):
            if not isinstance(entry, dict):
                continue
            family = str(entry.get("family") or "").lower()
            capabilities = entry.get("capabilities")
            if family == "z-image-turbo":
                entry["controlPolicy"] = {
                    "controls": [
                        {
                            "id": "canny",
                            "label": "Canny edges",
                            "status": "supported" if z_ready else "planned",
                            "inputKind": "source-image",
                            "preprocessor": "core-canny",
                            "strengthDefault": 1.0,
                            "cannyLowDefault": 0.4,
                            "cannyHighDefault": 0.8,
                        }
                    ],
                    "note": "Depth and pose follow after their preprocessors are pinned and target-tested.",
                }
                if isinstance(capabilities, dict) and z_ready:
                    capabilities["controlnet"] = "supported"
            elif family == "krea2":
                entry["controlPolicy"] = {
                    "controls": [
                        {
                            "id": "openpose",
                            "label": "OpenPose map",
                            "status": "supported" if k_ready else "planned",
                            "inputKind": "openpose-map",
                            "preprocessor": "precomputed",
                            "strengthDefault": 0.85,
                            "dependencyId": "krea2-openpose",
                            "installable": True,
                        }
                    ],
                    "note": "Depth is next; Krea 2 Turbo Canny remains gated until a Turbo-compatible route is accepted.",
                }
                if isinstance(capabilities, dict) and k_ready:
                    capabilities["controlnet"] = "supported"
        return support

    @staticmethod
    def _number(value: Any, default: float, minimum: float, maximum: float, label: str) -> float:
        try:
            number = float(default if value is None else value)
        except (TypeError, ValueError) as exc:
            raise base.StableAmdBridgeError(f"{label} must be numeric.") from exc
        if not math.isfinite(number) or number < minimum or number > maximum:
            raise base.StableAmdBridgeError(f"{label} must be between {minimum} and {maximum}.")
        return number

    def _control_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        value = request.get("control")
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("enabled", True) is False:
            return None
        return value

    def _inject_zimage_canny(self, workflow: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        for node_id in ("11", "29", "3"):
            if not isinstance(workflow.get(node_id), dict):
                raise base.StableAmdBridgeError("Z-Image workflow anchors are missing for Canny control.")
        sampler_model = workflow["11"].get("inputs", {}).get("model")
        if not isinstance(sampler_model, list):
            raise base.StableAmdBridgeError("Z-Image sampling model input is missing for Canny control.")

        patch_name = self._zimage_fun_patch_name(required=True)
        width = int(context["width"])
        height = int(context["height"])
        workflow["60"] = {"class_type": "LoadImage", "inputs": {"image": context["image_name"]}}
        workflow["61"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["60", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "center",
            },
        }
        workflow["62"] = {
            "class_type": "Canny",
            "inputs": {
                "image": ["61", 0],
                "low_threshold": float(context["canny_low"]),
                "high_threshold": float(context["canny_high"]),
            },
        }
        workflow["63"] = {"class_type": "ModelPatchLoader", "inputs": {"name": str(patch_name)}}
        workflow["64"] = {
            "class_type": "ZImageFunControlnet",
            "inputs": {
                "model": sampler_model,
                "model_patch": ["63", 0],
                "vae": ["29", 0],
                "strength": float(context["strength"]),
                "image": ["62", 0],
            },
        }
        workflow["11"]["inputs"]["model"] = ["64", 0]
        return workflow

    def _inject_krea_openpose(self, workflow: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        for node_id in ("10", "11", "12", "5", "3", "6"):
            if not isinstance(workflow.get(node_id), dict):
                raise base.StableAmdBridgeError("Krea 2 workflow anchors are missing for OpenPose control.")
        lora_name = self._lora_choice_by_leaf(KREA_OPENPOSE_LORA)
        if not lora_name:
            raise base.StableAmdBridgeError(
                f"ComfyUI does not expose '{KREA_OPENPOSE_LORA}'. Install the Krea 2 OpenPose dependency and restart the backend."
            )

        prompt = str(workflow["6"].get("inputs", {}).get("text") or "")
        current_model = workflow["3"].get("inputs", {}).get("model")
        if not isinstance(current_model, list):
            current_model = ["10", 0]
        width = int(context["width"])
        height = int(context["height"])

        workflow["60"] = {"class_type": "LoadImage", "inputs": {"image": context["image_name"]}}
        workflow["61"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["60", 0],
                "upscale_method": "nearest-exact",
                "width": width,
                "height": height,
                "crop": "center",
            },
        }
        workflow["62"] = {
            "class_type": "Krea2OstrisEditModelPatch",
            "inputs": {"model": current_model, "kv_cache": False},
        }
        workflow["63"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["62", 0],
                "lora_name": lora_name,
                "strength_model": float(context["strength"]),
            },
        }
        workflow["64"] = {
            "class_type": "TextEncodeKrea2OstrisEdit",
            "inputs": {
                "clip": ["11", 0],
                "prompt": prompt,
                "vae": ["12", 0],
                "image1": ["61", 0],
            },
        }
        workflow["65"] = {
            "class_type": "TextEncodeKrea2OstrisEdit",
            "inputs": {
                "clip": ["11", 0],
                "prompt": "",
                "vae": ["12", 0],
                "image1": ["61", 0],
            },
        }
        workflow["3"]["inputs"]["model"] = ["63", 0]
        workflow["3"]["inputs"]["positive"] = ["64", 0]
        workflow["3"]["inputs"]["negative"] = ["65", 0]
        return workflow

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        result = super()._run_script(name, parameters)
        context = self._active_control_context()
        if name != "Build-StableAmdWorkflow.ps1" or not context or not isinstance(result, dict):
            return result

        family = str(context.get("family") or "")
        control_type = str(context.get("type") or "")
        if family == "z-image-turbo" and control_type == "canny":
            return self._inject_zimage_canny(result, context)
        if family == "krea2" and control_type == "openpose":
            return self._inject_krea_openpose(result, context)
        return result

    def _persist_control_metadata(self, result: dict[str, Any], metadata: dict[str, Any]) -> None:
        raw = str(result.get("HistoryPath") or "").strip()
        if not raw:
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        path = Path(raw).resolve()
        if history_root not in path.parents or not path.is_file():
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record["mode"] = "controlnet"
            record["control"] = metadata
            temporary = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex}")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise base.StableAmdBridgeError(
                f"Controlled generation completed, but Gallery metadata could not be updated: {exc}"
            ) from exc

    def _generate_zimage_control(self, request: dict[str, Any], model: dict[str, Any], control: dict[str, Any]) -> Any:
        if str(control.get("type") or "").lower() != "canny":
            raise base.StableAmdBridgeError("Z-Image currently exposes Canny as its first StableAMD ControlNet route.")
        if not self._zimage_canny_ready():
            raise base.StableAmdBridgeError(
                "Z-Image Canny requires the curated Union 2.1 Lite patch and the pinned ComfyUI Canny/ZImageFunControlnet nodes."
            )
        if request.get("loraStack") or str(request.get("loraName") or "").strip():
            raise base.StableAmdBridgeError("Disable regular LoRAs for the first Z-Image Canny acceptance gate.")

        staged = base.stage_input_image(self.repo_root, control["image"])
        strength = self._number(control.get("strength"), 1.0, 0.0, 2.0, "Control strength")
        low = self._number(control.get("cannyLow"), 0.4, 0.01, 0.99, "Canny low threshold")
        high = self._number(control.get("cannyHigh"), 0.8, 0.01, 0.99, "Canny high threshold")
        if low >= high:
            staged.unlink(missing_ok=True)
            raise base.StableAmdBridgeError("Canny low threshold must be lower than the high threshold.")

        context = {
            "family": "z-image-turbo",
            "type": "canny",
            "image_name": staged.name,
            "width": int(request.get("width", 1024)),
            "height": int(request.get("height", 1024)),
            "strength": strength,
            "canny_low": low,
            "canny_high": high,
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
            "type": "canny",
            "inputName": str(control.get("image", {}).get("name") or "control-image"),
            "strength": strength,
            "cannyLow": low,
            "cannyHigh": high,
            "provider": "z-image-fun-control-union-2.1",
        }
        result["Mode"] = "controlnet"
        result["Control"] = metadata
        self._persist_control_metadata(result, metadata)
        return result

    def _generate_krea_control(self, request: dict[str, Any], model: dict[str, Any], control: dict[str, Any]) -> Any:
        if str(control.get("type") or "").lower() != "openpose":
            raise base.StableAmdBridgeError("Krea 2 Turbo currently exposes OpenPose-map control as its first StableAMD route.")
        if not self._krea_openpose_ready():
            raise base.StableAmdBridgeError(
                "Krea 2 OpenPose control is not ready. Install the curated Krea 2 OpenPose dependency and restart the backend."
            )

        staged = base.stage_input_image(self.repo_root, control["image"])
        strength = self._number(control.get("strength"), 0.85, 0.0, 2.0, "Control strength")
        context = {
            "family": "krea2",
            "type": "openpose",
            "image_name": staged.name,
            "width": int(request.get("width", 1024)),
            "height": int(request.get("height", 1024)),
            "strength": strength,
        }
        clean = dict(request)
        clean.pop("control", None)
        self._stableamd_control_context.value = context
        try:
            result = super()._generate_krea2_turbo(clean, model)
        finally:
            self._stableamd_control_context.value = None
            staged.unlink(missing_ok=True)

        metadata = {
            "type": "openpose",
            "inputKind": "precomputed-openpose-map",
            "inputName": str(control.get("image", {}).get("name") or "openpose-map"),
            "strength": strength,
            "provider": "krea2-ostris-openpose",
            "adapter": KREA_OPENPOSE_LORA,
        }
        result["Mode"] = "controlnet"
        result["Control"] = metadata
        self._persist_control_metadata(result, metadata)
        return result

    def generate(self, request: dict[str, Any]) -> Any:
        control = self._control_request(request)
        if control is None:
            return super().generate(request)
        if str(request.get("mode") or "txt2img").lower() != "txt2img":
            raise base.StableAmdBridgeError("Control guidance currently starts from txt2img mode only.")

        selected = self._selected_product_model(request)
        if not isinstance(selected, dict):
            raise base.StableAmdBridgeError("Select a supported Z-Image Turbo or Krea 2 Turbo model for control guidance.")
        family = str(selected.get("family") or selected.get("Family") or "").lower()
        if family == "z-image-turbo":
            return self._generate_zimage_control(request, selected, control)
        if family == "krea2":
            return self._generate_krea_control(request, selected, control)
        raise base.StableAmdBridgeError(
            f"StableAMD ControlNet is currently prioritized for Z-Image Turbo and Krea 2 Turbo, not '{family or 'unknown'}'."
        )


class ControlNetApiMixin:
    _generation_fields: set[str]
    _control_install_fields = {"id"}

    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        validated = super()._validate_generation(request)
        control = request.get("control")
        if control is None:
            return validated
        if not isinstance(control, dict):
            raise ValueError("control must be an object.")
        allowed = {"enabled", "type", "image", "strength", "cannyLow", "cannyHigh"}
        unsupported = sorted(set(control) - allowed)
        if unsupported:
            raise ValueError("Unsupported control field(s): " + ", ".join(unsupported))
        if "enabled" in control and not isinstance(control["enabled"], bool):
            raise ValueError("control.enabled must be boolean.")
        if control.get("enabled", True) is False:
            return validated
        control_type = control.get("type")
        if not isinstance(control_type, str) or control_type.lower() not in {"canny", "openpose"}:
            raise ValueError("control.type must be 'canny' or 'openpose' for the current v0.3 gate.")
        if "image" not in control:
            raise ValueError("Control guidance requires control.image.")
        base._decode_input_image(control["image"])
        for field in ("strength", "cannyLow", "cannyHigh"):
            if field in control:
                value = control[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"control.{field} must be numeric.")
        return validated

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        try:
            if method == "GET" and path == "/api/controlnet/dependencies":
                return 200, self.bridge.controlnet_dependencies()
            if method == "POST" and path == "/api/controlnet/install":
                request = self._decode_json(body)
                unsupported = sorted(set(request) - self._control_install_fields)
                if unsupported:
                    raise ValueError("Unsupported ControlNet install field(s): " + ", ".join(unsupported))
                dependency_id = request.get("id")
                if not isinstance(dependency_id, str) or not dependency_id.strip():
                    raise ValueError("ControlNet dependency id is required.")
                return 200, self.bridge.install_controlnet_dependency(dependency_id.strip())
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return super().dispatch(method, target, body)
