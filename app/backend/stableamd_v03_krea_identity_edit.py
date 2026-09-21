from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path
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
