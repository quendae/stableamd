from __future__ import annotations

import sys
from pathlib import Path

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

# A source image plus one 20 MiB reference image expands to roughly 54 MiB once
# both are base64-encoded inside JSON. Keep the loopback-only request budget
# comfortably above that without changing the per-image 20 MiB validation.
base.MAX_REQUEST_BYTES = max(base.MAX_REQUEST_BYTES, 64 * 1024 * 1024)


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


class StableAmdApi(
    GenerationJobsApiMixin,
    PoseExtractApiMixin,
    DepthControlApiMixin,
    ControlNetApiMixin,
    product.StableAmdApi,
):
    _generation_fields = set(product.StableAmdApi._generation_fields) | {"control", "asyncJob", "references"}
    _reference_roles = {"style", "material", "content"}

    def _validate_generation(self, request):
        if "references" not in request:
            return super()._validate_generation(request)

        references = request.get("references")
        clean = dict(request)
        clean.pop("references", None)
        validated = super()._validate_generation(clean)

        if validated.get("mode", "txt2img") != "img2img":
            raise ValueError("Reference images are valid only for img2img generation.")
        if not isinstance(references, list):
            raise ValueError("references must be an array.")
        if len(references) > 1:
            raise ValueError("Krea Image Edit currently accepts at most 1 reference image.")
        if not references:
            return validated

        reference = references[0]
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

        validated["references"] = references
        return validated


base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
