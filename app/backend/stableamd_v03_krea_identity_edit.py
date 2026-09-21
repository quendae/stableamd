from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path
from threading import local
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import stableamd_v03_controlnet as controlnet

base = controlnet.base

KREA_IDENTITY_DEPENDENCY_ID = "krea2-identity-edit-v1.2"
KREA_IDENTITY_PLUGIN_REPOSITORY = "https://github.com/lbouaraba/comfyui-krea2edit.git"
KREA_IDENTITY_PLUGIN_COMMIT = "86f886dac23013d88996e3a2e99093ba44d322fb"
KREA_IDENTITY_PLUGIN_LICENSE = "Apache-2.0"
KREA_IDENTITY_LORA_REPOSITORY = "conradlocke/krea2-identity-edit"
KREA_IDENTITY_LORA_REVISION = "main"
KREA_IDENTITY_LORA_FILENAME = "krea2_identity_edit_v1_2.safetensors"
KREA_IDENTITY_LORA_LICENSE = "Krea 2 Community License"
KREA_IDENTITY_LORA_BYTES = 1_828_256_432
KREA_IDENTITY_LORA_SHA256 = "6adf9a69cc9502d286db7b69964d37da7e9cfe4b05b4d004bc275f087d3fd3cf"
KREA_IDENTITY_LORA_URL = (
    "https://huggingface.co/conradlocke/krea2-identity-edit/resolve/main/"
    "krea2_identity_edit_v1_2.safetensors?download=true"
)
KREA_IDENTITY_REQUIRED_NODES = (
    "Krea2EditModelPatch",
    "Krea2EditGroundedEncode",
    "LoraLoaderModelOnly",
)
KREA_IDENTITY_LORA_STRENGTH = 1.0
KREA_IDENTITY_REF_BOOST = 4.0
KREA_IDENTITY_SCENE_REF_BOOST = 1.0
KREA_IDENTITY_GROUNDING_PX = 1024
KREA_IDENTITY_BASE_WIDTH = 1792
KREA_IDENTITY_BASE_HEIGHT = 1024
KREA_IDENTITY_BASE_STEPS = 10
KREA_IDENTITY_MAX_PIXELS = 2_000_000
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_identity_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "huggingface.co":
        raise base.StableAmdBridgeError("Krea Identity Edit downloads are restricted to huggingface.co over HTTPS.")
    expected_prefix = f"/{KREA_IDENTITY_LORA_REPOSITORY}/resolve/{KREA_IDENTITY_LORA_REVISION}/"
    if not parsed.path.startswith(expected_prefix) or not parsed.path.endswith("/" + KREA_IDENTITY_LORA_FILENAME):
        raise base.StableAmdBridgeError("Krea Identity Edit download URL is outside the pinned model path.")


def _download_pinned_identity_lora(destination: Path) -> bool:
    _validate_identity_download_url(KREA_IDENTITY_LORA_URL)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if destination.stat().st_size != KREA_IDENTITY_LORA_BYTES or _sha256_file(destination) != KREA_IDENTITY_LORA_SHA256:
            raise base.StableAmdBridgeError(
                f"A different or corrupt Identity Edit LoRA exists at '{destination}'. Move it aside before installation."
            )
        return False

    temporary = destination.with_name(f".{destination.name}.partial-{uuid.uuid4().hex}")
    digest = hashlib.sha256()
    total = 0
    request = Request(
        KREA_IDENTITY_LORA_URL,
        headers={"User-Agent": "StableAMD/0.3 krea-identity-installer"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > KREA_IDENTITY_LORA_BYTES:
                    raise base.StableAmdBridgeError("Identity Edit download exceeded its pinned expected size.")
                digest.update(chunk)
                output.write(chunk)
        if total != KREA_IDENTITY_LORA_BYTES:
            raise base.StableAmdBridgeError(
                f"Identity Edit size mismatch: expected {KREA_IDENTITY_LORA_BYTES} bytes, received {total}."
            )
        if digest.hexdigest() != KREA_IDENTITY_LORA_SHA256:
            raise base.StableAmdBridgeError("Identity Edit checksum mismatch. The downloaded file was not installed.")
        temporary.replace(destination)
        return True
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class KreaIdentityEditBridgeMixin:
    def __post_init__(self) -> None:
        super().__post_init__()
        self._stableamd_krea_identity_context = local()

    def _active_krea_identity_context(self) -> dict[str, Any] | None:
        storage = getattr(self, "_stableamd_krea_identity_context", None)
        value = getattr(storage, "value", None) if storage is not None else None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _dependency_descriptor_static() -> dict[str, Any]:
        return {
            "id": KREA_IDENTITY_DEPENDENCY_ID,
            "name": "Krea 2 Identity Edit v1.2",
            "family": "krea2",
            "type": "identity-edit",
            "installable": True,
            "restartRequired": True,
            "plugin": {
                "repository": KREA_IDENTITY_PLUGIN_REPOSITORY,
                "commit": KREA_IDENTITY_PLUGIN_COMMIT,
                "license": KREA_IDENTITY_PLUGIN_LICENSE,
            },
            "model": {
                "repository": KREA_IDENTITY_LORA_REPOSITORY,
                "revision": KREA_IDENTITY_LORA_REVISION,
                "filename": KREA_IDENTITY_LORA_FILENAME,
                "sizeBytes": KREA_IDENTITY_LORA_BYTES,
                "sha256": KREA_IDENTITY_LORA_SHA256,
                "license": KREA_IDENTITY_LORA_LICENSE,
            },
            "requiredNodes": list(KREA_IDENTITY_REQUIRED_NODES),
        }

    def _krea_identity_plugin_root(self) -> Path:
        return (
            self.repo_root
            / ".runtime"
            / "therock-comfy"
            / "ComfyUI"
            / "custom_nodes"
            / "comfyui-krea2edit"
        ).resolve()

    def _krea_identity_lora_path(self) -> Path:
        return (
            self.repo_root
            / ".runtime"
            / "stableamd"
            / "models"
            / "loras"
            / "krea"
            / KREA_IDENTITY_LORA_FILENAME
        ).resolve()

    def _krea_identity_plugin_at_pin(self) -> bool:
        root = self._krea_identity_plugin_root()
        if not root.is_dir() or not (root / ".git").exists():
            return False
        git = shutil.which("git.exe") or shutil.which("git")
        if not git:
            return False
        try:
            completed = subprocess.run(
                [git, "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0 and completed.stdout.strip().lower() == KREA_IDENTITY_PLUGIN_COMMIT.lower()

    def _krea_identity_lora_integrity(self) -> str:
        path = self._krea_identity_lora_path()
        if not path.is_file():
            return "missing"
        if path.stat().st_size != KREA_IDENTITY_LORA_BYTES:
            return "size-mismatch"
        try:
            return "ok" if _sha256_file(path) == KREA_IDENTITY_LORA_SHA256 else "checksum-mismatch"
        except OSError:
            return "unreadable"

    def _krea_identity_edit_ready(self) -> bool:
        return all(self._node_available(name) for name in KREA_IDENTITY_REQUIRED_NODES) and (
            self._lora_choice_by_leaf(KREA_IDENTITY_LORA_FILENAME) is not None
        )

    @staticmethod
    def _validate_identity_target(width: Any, height: Any) -> tuple[int, int]:
        try:
            w = int(width)
            h = int(height)
        except (TypeError, ValueError) as exc:
            raise base.StableAmdBridgeError("Krea Identity Edit dimensions must be integers.") from exc
        if w <= 0 or h <= 0 or w % 16 or h % 16:
            raise base.StableAmdBridgeError("Krea Identity Edit dimensions must be positive and divisible by 16.")
        if w * h >= KREA_IDENTITY_MAX_PIXELS:
            raise base.StableAmdBridgeError("Krea Identity Edit target must stay below the 2 MP quality ceiling.")
        return w, h

    def _inject_krea_identity_edit(
        self,
        workflow: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        for node_id in ("3", "5", "6", "7", "8", "10", "11", "12"):
            if not isinstance(workflow.get(node_id), dict):
                raise base.StableAmdBridgeError(
                    "Krea 2 workflow anchors are missing for Identity Edit."
                )
        for node_name in KREA_IDENTITY_REQUIRED_NODES:
            if not self._node_available(node_name):
                raise base.StableAmdBridgeError(
                    f"Krea Identity Edit requires ComfyUI node '{node_name}'. Install the pinned dependency and restart ComfyUI."
                )

        lora_name = self._lora_choice_by_leaf(KREA_IDENTITY_LORA_FILENAME)
        if not lora_name:
            raise base.StableAmdBridgeError(
                f"ComfyUI does not expose '{KREA_IDENTITY_LORA_FILENAME}'. Install the Krea Identity Edit dependency and restart ComfyUI."
            )

        image_name = str(context.get("image_name") or "").strip()
        identity_image_name = str(context.get("identity_image_name") or "").strip()
        if not image_name:
            raise base.StableAmdBridgeError("Krea Identity Edit source image is missing.")
        width, height = self._validate_identity_target(
            context.get("width", KREA_IDENTITY_BASE_WIDTH),
            context.get("height", KREA_IDENTITY_BASE_HEIGHT),
        )
        prompt = str(context.get("prompt") or "").strip()
        if not prompt:
            raise base.StableAmdBridgeError("Krea Identity Edit prompt is required.")

        sampler_inputs = workflow["3"].get("inputs")
        latent_inputs = workflow["5"].get("inputs")
        decode_inputs = workflow["8"].get("inputs")
        if not all(isinstance(value, dict) for value in (sampler_inputs, latent_inputs, decode_inputs)):
            raise base.StableAmdBridgeError("Krea 2 workflow inputs are incomplete for Identity Edit.")

        current_model = sampler_inputs.get("model")
        if not isinstance(current_model, list):
            current_model = ["10", 0]

        latent_inputs["width"] = width
        latent_inputs["height"] = height
        latent_inputs["batch_size"] = 1
        sampler_inputs["steps"] = KREA_IDENTITY_BASE_STEPS
        sampler_inputs["cfg"] = 1.0
        sampler_inputs["sampler_name"] = "euler"
        sampler_inputs["scheduler"] = "simple"
        sampler_inputs["denoise"] = 1.0

        workflow["120"] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        }
        # Krea2EditModelPatch uses the raw IMAGE through its pixel path and
        # re-encodes it at the target grid. Its required source_latent socket is
        # still evaluated first by ComfyUI, so never feed a camera-resolution
        # source directly to WanVAE: on CPU VAE that can create tens-of-GB
        # attention allocations before the safe pixel path gets a chance to run.
        workflow["127"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["120", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "center",
            },
        }
        workflow["121"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["127", 0], "vae": ["12", 0]},
        }
        if identity_image_name:
            workflow["122"] = {
                "class_type": "LoadImage",
                "inputs": {"image": identity_image_name},
            }
            workflow["128"] = {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["122", 0],
                    "upscale_method": "lanczos",
                    "width": width,
                    "height": height,
                    "crop": "center",
                },
            }
            workflow["123"] = {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["128", 0], "vae": ["12", 0]},
            }

        workflow["124"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": current_model,
                "lora_name": lora_name,
                "strength_model": KREA_IDENTITY_LORA_STRENGTH,
            },
        }
        patch_inputs: dict[str, Any] = {
            "model": ["124", 0],
            "source_latent": ["121", 0],
            "ref_boost": KREA_IDENTITY_REF_BOOST,
            "ref_boost_a": KREA_IDENTITY_SCENE_REF_BOOST,
            "fit_mode": "fit",
            "vae": ["12", 0],
            "source_image": ["120", 0],
            "target_latent": ["5", 0],
        }
        if identity_image_name:
            patch_inputs["source_latent_b"] = ["123", 0]
            patch_inputs["source_image_b"] = ["122", 0]
        workflow["125"] = {
            "class_type": "Krea2EditModelPatch",
            "inputs": patch_inputs,
        }

        grounded_inputs: dict[str, Any] = {
            "clip": ["11", 0],
            "prompt": prompt,
            "image": ["120", 0],
            "grounding_px": KREA_IDENTITY_GROUNDING_PX,
        }
        if identity_image_name:
            grounded_inputs["image_b"] = ["122", 0]
        workflow["126"] = {
            "class_type": "Krea2EditGroundedEncode",
            "inputs": grounded_inputs,
        }

        sampler_inputs["model"] = ["125", 0]
        sampler_inputs["positive"] = ["126", 0]
        # CFG 1 uses the accepted empty text conditioning and avoids needless
        # duplicate image-grounded encoding on the negative branch.
        sampler_inputs["negative"] = ["7", 0]
        decode_inputs["vae"] = ["12", 0]
        return workflow

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        result = super()._run_script(name, parameters)
        context = self._active_krea_identity_context()
        if name != "Build-StableAmdWorkflow.ps1" or not context or not isinstance(result, dict):
            return result
        return self._inject_krea_identity_edit(result, context)

    def krea_identity_dependency(self) -> dict[str, Any]:
        descriptor = self._dependency_descriptor_static()
        plugin_root = self._krea_identity_plugin_root()
        lora_path = self._krea_identity_lora_path()
        ready = self._krea_identity_edit_ready()
        descriptor["ready"] = ready
        descriptor["restartRequired"] = bool((plugin_root.exists() or lora_path.exists()) and not ready)
        descriptor["plugin"]["installedOnDisk"] = plugin_root.is_dir()
        descriptor["plugin"]["pinnedRevision"] = self._krea_identity_plugin_at_pin()
        descriptor["model"]["installedOnDisk"] = lora_path.is_file()
        descriptor["model"]["integrity"] = self._krea_identity_lora_integrity()
        return descriptor

    def _install_identity_plugin(self) -> bool:
        git = shutil.which("git.exe") or shutil.which("git")
        if not git:
            raise base.StableAmdBridgeError("Git is required to install the pinned Krea Identity Edit ComfyUI integration.")

        plugin_root = self._krea_identity_plugin_root()
        custom_nodes = plugin_root.parent
        custom_nodes.mkdir(parents=True, exist_ok=True)
        if plugin_root.exists():
            if not plugin_root.is_dir() or not (plugin_root / ".git").exists():
                raise base.StableAmdBridgeError(
                    f"'{plugin_root}' exists but is not the managed Git checkout. Move it aside before installation."
                )
            head = subprocess.run(
                [git, "-C", str(plugin_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if head.returncode != 0 or head.stdout.strip().lower() != KREA_IDENTITY_PLUGIN_COMMIT.lower():
                raise base.StableAmdBridgeError(
                    "Krea Identity Edit node pack exists at another revision. StableAMD will not overwrite it."
                )
            return False

        temporary = custom_nodes / f".stableamd-krea2-identity-{uuid.uuid4().hex}"
        try:
            clone = subprocess.run(
                [git, "clone", "--filter=blob:none", "--no-checkout", KREA_IDENTITY_PLUGIN_REPOSITORY, str(temporary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            if clone.returncode != 0:
                raise base.StableAmdBridgeError((clone.stderr or clone.stdout or "git clone failed").strip())
            checkout = subprocess.run(
                [git, "-C", str(temporary), "checkout", "--detach", KREA_IDENTITY_PLUGIN_COMMIT],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if checkout.returncode != 0:
                raise base.StableAmdBridgeError((checkout.stderr or checkout.stdout or "git checkout failed").strip())
            temporary.replace(plugin_root)
            return True
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def install_krea_identity_dependency(self) -> dict[str, Any]:
        plugin_changed = self._install_identity_plugin()
        lora_path = self._krea_identity_lora_path()
        lora_changed = _download_pinned_identity_lora(lora_path)
        ready = self._krea_identity_edit_ready()
        return {
            "id": KREA_IDENTITY_DEPENDENCY_ID,
            "installed": True,
            "pluginChanged": plugin_changed,
            "modelChanged": lora_changed,
            "pluginCommit": KREA_IDENTITY_PLUGIN_COMMIT,
            "modelPath": str(lora_path),
            "modelSha256": KREA_IDENTITY_LORA_SHA256,
            "ready": ready,
            "restartRequired": bool(plugin_changed or lora_changed or not ready),
        }


class KreaIdentityEditApiMixin:
    _krea_identity_install_fields = {"id"}

    def dispatch(self, method: str, target: str, body: bytes | None = None):
        path = target.split("?", 1)[0]
        verb = method.upper()
        try:
            if verb == "GET" and path == "/api/krea-identity/dependency":
                return 200, self.bridge.krea_identity_dependency()
            if verb == "POST" and path == "/api/krea-identity/install":
                request = self._decode_json(body)
                unsupported = sorted(set(request) - self._krea_identity_install_fields)
                if unsupported:
                    raise ValueError("Unsupported Krea Identity install field(s): " + ", ".join(unsupported))
                dependency_id = request.get("id", KREA_IDENTITY_DEPENDENCY_ID)
                if dependency_id != KREA_IDENTITY_DEPENDENCY_ID:
                    raise ValueError(f"Krea Identity dependency id must be '{KREA_IDENTITY_DEPENDENCY_ID}'.")
                return 200, self.bridge.install_krea_identity_dependency()
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except base.StableAmdBridgeError as exc:
            return 409, {"error": str(exc)}
        return super().dispatch(method, target, body)
