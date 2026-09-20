from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

# The managed Windows runtime uses the embeddable Python distribution with a
# restricted module search path. Bootstrap sibling modules before importing the
# preserved product server, just like the accepted v0.3 wrapper did.
BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Keep the previous final v0.3 product server intact as a compatibility layer,
# then add Krea Image Edit, pose extraction, Depth/ControlNet, pose-control and
# async job extensions. This keeps the accepted Krea LoRA, Z-Image edit and
# hardened PowerShell transport paths intact.
from stableamd_v03_product_server import *  # noqa: F401,F403,E402
import stableamd_v03_product_server as product  # noqa: E402
import stableamd_v03_controlnet as controlnet  # noqa: E402
import stableamd_v03_pose_control as posecontrol  # noqa: E402
import stableamd_v03_depth_control as depthcontrol  # noqa: E402
import stableamd_v03_pose_extract as poseextract  # noqa: E402
import stableamd_v03_krea_edit as kreaedit  # noqa: E402
from stableamd_generation_jobs import GenerationJobsApiMixin, GenerationTimeoutBridgeMixin  # noqa: E402
from stableamd_v03_controlnet import ControlNetApiMixin, ControlNetBridgeMixin  # noqa: E402
from stableamd_v03_pose_control import PoseControlBridgeMixin  # noqa: E402
from stableamd_v03_depth_control import DepthControlApiMixin, DepthControlBridgeMixin  # noqa: E402
from stableamd_v03_pose_extract import PoseExtractApiMixin, PoseExtractBridgeMixin  # noqa: E402
from stableamd_v03_krea_edit import KreaImageEditBridgeMixin  # noqa: E402

COMFYUI_RELEASES_URL = "https://api.github.com/repos/Comfy-Org/ComfyUI/releases/latest"

# Explicit compatibility exports used by the regression suite.
base = product.base
editing = product.editing
features = product.features
shutil = product.shutil
subprocess = product.subprocess
_POWERSHELL_JSON_SENTINEL = product._POWERSHELL_JSON_SENTINEL
ZIMAGE_FUN_PATCH = product.ZIMAGE_FUN_PATCH
ZIMAGE_FUN_LEGACY_PATCH = product.ZIMAGE_FUN_LEGACY_PATCH
ZIMAGE_FUN_PATCH_SHA256 = product.ZIMAGE_FUN_PATCH_SHA256
ZIMAGE_FUN_PATCH_BYTES = product.ZIMAGE_FUN_PATCH_BYTES
KREA_OPENPOSE_PLUGIN_REPO = controlnet.KREA_OPENPOSE_PLUGIN_REPO
KREA_OPENPOSE_PLUGIN_COMMIT = controlnet.KREA_OPENPOSE_PLUGIN_COMMIT
KREA_OPENPOSE_LORA = controlnet.KREA_OPENPOSE_LORA
KREA_OPENPOSE_LORA_URL = controlnet.KREA_OPENPOSE_LORA_URL
KREA_OPENPOSE_LORA_BYTES = controlnet.KREA_OPENPOSE_LORA_BYTES
KREA_OPENPOSE_LORA_SHA256 = controlnet.KREA_OPENPOSE_LORA_SHA256
DEPTH_ANYTHING_DEPENDENCY_ID = depthcontrol.DEPTH_ANYTHING_DEPENDENCY_ID
DEPTH_ANYTHING_REPOSITORY = depthcontrol.DEPTH_ANYTHING_REPOSITORY
DEPTH_ANYTHING_REVISION = depthcontrol.DEPTH_ANYTHING_REVISION
DEPTH_ANYTHING_MODEL_FILENAME = depthcontrol.DEPTH_ANYTHING_MODEL_FILENAME
DEPTH_ANYTHING_MODEL_URL = depthcontrol.DEPTH_ANYTHING_MODEL_URL
DEPTH_ANYTHING_MODEL_BYTES = depthcontrol.DEPTH_ANYTHING_MODEL_BYTES
DEPTH_ANYTHING_MODEL_SHA256 = depthcontrol.DEPTH_ANYTHING_MODEL_SHA256
DEPTH_ANYTHING_LICENSE = depthcontrol.DEPTH_ANYTHING_LICENSE
KREA_DEPTH_DEPENDENCY_ID = depthcontrol.KREA_DEPTH_DEPENDENCY_ID
KREA_DEPTH_PLUGIN_REPOSITORY = depthcontrol.KREA_DEPTH_PLUGIN_REPOSITORY
KREA_DEPTH_PLUGIN_COMMIT = depthcontrol.KREA_DEPTH_PLUGIN_COMMIT
KREA_DEPTH_PLUGIN_LICENSE = depthcontrol.KREA_DEPTH_PLUGIN_LICENSE
KREA_DEPTH_LORA_REPOSITORY = depthcontrol.KREA_DEPTH_LORA_REPOSITORY
KREA_DEPTH_LORA_REVISION = depthcontrol.KREA_DEPTH_LORA_REVISION
KREA_DEPTH_LORA_FILENAME = depthcontrol.KREA_DEPTH_LORA_FILENAME
KREA_DEPTH_LORA_URL = depthcontrol.KREA_DEPTH_LORA_URL
KREA_DEPTH_LORA_BYTES = depthcontrol.KREA_DEPTH_LORA_BYTES
KREA_DEPTH_LORA_SHA256 = depthcontrol.KREA_DEPTH_LORA_SHA256
KREA_DEPTH_LORA_LICENSE = depthcontrol.KREA_DEPTH_LORA_LICENSE
DWPOSE_DEPENDENCY_ID = poseextract.DWPOSE_DEPENDENCY_ID
DWPOSE_SOURCE_REPOSITORY = poseextract.DWPOSE_SOURCE_REPOSITORY
DWPOSE_SOURCE_COMMIT = poseextract.DWPOSE_SOURCE_COMMIT
DWPOSE_SOURCE_LICENSE = poseextract.DWPOSE_SOURCE_LICENSE
DWPOSE_MODEL_REPOSITORY = poseextract.DWPOSE_MODEL_REPOSITORY
DWPOSE_MODEL_REVISION = poseextract.DWPOSE_MODEL_REVISION
DWPOSE_DETECTOR_FILENAME = poseextract.DWPOSE_DETECTOR_FILENAME
DWPOSE_DETECTOR_BYTES = poseextract.DWPOSE_DETECTOR_BYTES
DWPOSE_DETECTOR_SHA256 = poseextract.DWPOSE_DETECTOR_SHA256
DWPOSE_POSE_FILENAME = poseextract.DWPOSE_POSE_FILENAME
DWPOSE_POSE_BYTES = poseextract.DWPOSE_POSE_BYTES
DWPOSE_POSE_SHA256 = poseextract.DWPOSE_POSE_SHA256
DWPOSE_LICENSE = poseextract.DWPOSE_LICENSE
DWPOSE_ONNXRUNTIME_VERSION = poseextract.DWPOSE_ONNXRUNTIME_VERSION
DWPOSE_OPENCV_VERSION = poseextract.DWPOSE_OPENCV_VERSION

# A source image plus two 20 MiB reference images expands to roughly 80 MiB once
# all three are base64-encoded inside JSON. Keep the loopback-only request budget
# comfortably above that without changing the per-image 20 MiB validation.
base.MAX_REQUEST_BYTES = max(base.MAX_REQUEST_BYTES, 96 * 1024 * 1024)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _version_tuple(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    match = re.match(r"^v?(\d+(?:\.\d+)+)", str(value).strip())
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def _read_comfy_version(comfy_root: Path) -> str | None:
    candidates = [
        comfy_root / "comfyui_version.py",
        comfy_root / "comfy" / "comfyui_version.py",
        comfy_root / "pyproject.toml",
    ]
    patterns = [
        re.compile(r"__version__\s*=\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"(?m)^version\s*=\s*['\"]([^'\"]+)['\"]"),
    ]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
    return None


class PowerShellBridge(
    KreaImageEditBridgeMixin,
    PoseExtractBridgeMixin,
    DepthControlBridgeMixin,
    PoseControlBridgeMixin,
    ControlNetBridgeMixin,
    GenerationTimeoutBridgeMixin,
    product.PowerShellBridge,
):
    """Final v0.3 bridge: accepted product paths + provider controls/preprocessors."""

    def _node_available(self, node_name: str) -> bool:
        # Capability discovery must never turn an otherwise valid model-support
        # response into an error. Compatibility test bridges intentionally
        # expose only the nodes they know about; real ComfyUI can likewise be
        # temporarily unavailable during restart.
        try:
            return super()._node_available(node_name)
        except Exception:
            return False

    def _lora_choice_by_leaf(self, filename: str, node_name: str = "LoraLoaderModelOnly"):
        try:
            return super()._lora_choice_by_leaf(filename, node_name)
        except Exception:
            return None

    def comfyui_runtime(self):
        lock = _read_json(self.repo_root / "config" / "runtime-lock.v0.1.json")
        runtime_lock = lock.get("runtime") if isinstance(lock.get("runtime"), dict) else {}
        pinned_version = str(runtime_lock.get("comfyui") or "") or None
        pinned_commit = str(runtime_lock.get("comfyCommit") or "") or None

        comfy_root = self.repo_root / ".runtime" / "therock-comfy" / "ComfyUI"
        installed_commit = None
        if comfy_root.is_dir():
            try:
                completed = subprocess.run(
                    ["git", "-C", str(comfy_root), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
                if completed.returncode == 0 and completed.stdout.strip():
                    installed_commit = completed.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                installed_commit = None

        installed_version = _read_comfy_version(comfy_root) if comfy_root.is_dir() else None
        if not installed_version and installed_commit and pinned_commit and installed_commit.lower() == pinned_commit.lower():
            installed_version = pinned_version

        backend_url = "http://127.0.0.1:8190/"
        state = _read_json(self.repo_root / ".runtime" / "stableamd" / "backend-state.json")
        state_url = state.get("url")
        if isinstance(state_url, str) and state_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            backend_url = state_url if state_url.endswith("/") else state_url + "/"
        else:
            config = _read_json(self.repo_root / ".runtime" / "stableamd" / "config.json")
            if not config:
                config = _read_json(self.repo_root / "config" / "stableamd.default.json")
            backend = config.get("backend") if isinstance(config.get("backend"), dict) else {}
            try:
                port = int(backend.get("port") or 8190)
                if 1 <= port <= 65535:
                    backend_url = f"http://127.0.0.1:{port}/"
            except (TypeError, ValueError):
                pass

        latest = None
        latest_check = "unavailable"
        try:
            request = Request(
                COMFYUI_RELEASES_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "StableAMD-v0.3-runtime-check",
                },
            )
            with urlopen(request, timeout=3) as response:
                release = json.loads(response.read().decode("utf-8"))
            if isinstance(release, dict):
                tag = str(release.get("tag_name") or "").strip()
                version = tag[1:] if tag.lower().startswith("v") else tag
                if version:
                    latest = {
                        "version": version,
                        "tag": tag or version,
                        "url": str(release.get("html_url") or ""),
                        "publishedAt": release.get("published_at"),
                    }
                    latest_check = "ok"
        except Exception:
            latest = None
            latest_check = "unavailable"

        installed_tuple = _version_tuple(installed_version)
        latest_tuple = _version_tuple(latest.get("version") if latest else None)
        update_available = None
        if installed_tuple is not None and latest_tuple is not None:
            update_available = latest_tuple > installed_tuple

        pin_matches = None
        if installed_commit and pinned_commit:
            pin_matches = installed_commit.lower() == pinned_commit.lower()

        return {
            "backendUrl": backend_url,
            "installed": {
                "version": installed_version,
                "commit": installed_commit,
                "path": str(comfy_root),
            },
            "pinned": {
                "version": pinned_version,
                "commit": pinned_commit,
            },
            "latest": latest,
            "latestCheck": latest_check,
            "updateAvailable": update_available,
            "pinMatchesCheckout": pin_matches,
        }


class StableAmdApi(
    GenerationJobsApiMixin,
    PoseExtractApiMixin,
    DepthControlApiMixin,
    ControlNetApiMixin,
    product.StableAmdApi,
):
    _generation_fields = set(product.StableAmdApi._generation_fields) | {"control", "asyncJob", "references", "editTask"}
    _reference_roles = {"style", "material", "content"}
    _edit_tasks = {"character-turnaround"}

    def dispatch(self, method: str, target: str, body: bytes | None = None):
        if method.upper() == "GET" and target.split("?", 1)[0] == "/api/comfyui-runtime":
            return 200, self.bridge.comfyui_runtime()
        return super().dispatch(method, target, body)

    def _validate_generation(self, request):
        has_references = "references" in request
        references = request.get("references")
        edit_task = request.get("editTask")

        clean = dict(request)
        clean.pop("references", None)
        clean.pop("editTask", None)
        validated = super()._validate_generation(clean)

        if edit_task is not None:
            if not isinstance(edit_task, str) or edit_task not in self._edit_tasks:
                raise ValueError("editTask must be character-turnaround when provided.")
            if validated.get("mode", "txt2img") != "img2img":
                raise ValueError("editTask is valid only for img2img generation.")
            validated["editTask"] = edit_task

        if not has_references:
            return validated

        if validated.get("mode", "txt2img") != "img2img":
            raise ValueError("Reference images are valid only for img2img generation.")
        if not isinstance(references, list):
            raise ValueError("references must be an array.")
        if len(references) > 2:
            raise ValueError("Krea Image Edit currently accepts at most 2 reference images.")
        if edit_task == "character-turnaround" and references:
            raise ValueError("Character turnaround does not accept extra reference images.")

        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError("Reference image entry must be an object.")
            unsupported = sorted(set(reference) - {"role", "image"})
            if unsupported:
                raise ValueError("Unsupported reference image field(s): " + ", ".join(unsupported))
            role = reference.get("role")
            if not isinstance(role, str) or role not in self._reference_roles:
                raise ValueError("Reference image role must be style, material, or content.")
            if "image" not in reference:
                raise ValueError("Reference image entry requires image.")
            base._decode_input_image(reference["image"])

        if references:
            validated["references"] = references
        return validated


base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
