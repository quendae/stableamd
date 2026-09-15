from __future__ import annotations

# Keep the previous final v0.3 product server intact as a compatibility layer,
# then add ControlNet as one more extension. This keeps the accepted Krea LoRA,
# Z-Image edit and hardened PowerShell transport paths unchanged.
from stableamd_v03_product_server import *  # noqa: F401,F403
import stableamd_v03_product_server as product
from stableamd_v03_controlnet import ControlNetApiMixin, ControlNetBridgeMixin

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


class PowerShellBridge(ControlNetBridgeMixin, product.PowerShellBridge):
    """Final v0.3 bridge: accepted product paths + provider-aware ControlNet."""


class StableAmdApi(ControlNetApiMixin, product.StableAmdApi):
    _generation_fields = set(product.StableAmdApi._generation_fields) | {"control"}


base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
