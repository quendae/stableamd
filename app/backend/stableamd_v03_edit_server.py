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
# then add ControlNet as one more extension. This keeps the accepted Krea LoRA,
# Z-Image edit and hardened PowerShell transport paths unchanged.
from stableamd_v03_product_server import *  # noqa: F401,F403,E402
import stableamd_v03_product_server as product  # noqa: E402
import stableamd_v03_controlnet as controlnet  # noqa: E402
from stableamd_v03_controlnet import ControlNetApiMixin, ControlNetBridgeMixin  # noqa: E402

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


class PowerShellBridge(ControlNetBridgeMixin, product.PowerShellBridge):
    """Final v0.3 bridge: accepted product paths + provider-aware ControlNet."""

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


class StableAmdApi(ControlNetApiMixin, product.StableAmdApi):
    _generation_fields = set(product.StableAmdApi._generation_fields) | {"control"}


base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
