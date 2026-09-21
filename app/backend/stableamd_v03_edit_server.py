from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_v03_edit_server_legacy import *  # noqa: F401,F403,E402
import stableamd_v03_edit_server_legacy as legacy  # noqa: E402
import stableamd_v03_product_server as product  # noqa: F401,E402
import stableamd_v03_krea_edit as kreaedit  # noqa: E402
from stableamd_generation_jobs import GenerationJobsApiMixin, GenerationTimeoutBridgeMixin  # noqa: F401,E402
from stableamd_v03_krea_edit import KreaImageEditBridgeMixin  # noqa: F401,E402
from stableamd_v03_controlnet import ControlNetApiMixin, ControlNetBridgeMixin  # noqa: F401,E402
from stableamd_v03_depth_control import DepthControlApiMixin, DepthControlBridgeMixin  # noqa: F401,E402
from stableamd_v03_pose_control import PoseControlBridgeMixin  # noqa: F401,E402
from stableamd_v03_krea_identity_edit import (  # noqa: E402
    KreaIdentityEditApiMixin,
    KreaIdentityEditBridgeMixin,
)

# Explicit aliases retained for compatibility with tests and downstream modules
# that import the final v0.3 server rather than the preserved legacy layer.
base = legacy.base
editing = legacy.editing
features = legacy.features
shutil = legacy.shutil
subprocess = legacy.subprocess
_POWERSHELL_JSON_SENTINEL = legacy._POWERSHELL_JSON_SENTINEL
COMFYUI_RELEASES_URL = legacy.COMFYUI_RELEASES_URL

# Keep the source-level composition contract visible in the final wrapper. The
# actual instances are inherited once through legacy.PowerShellBridge, avoiding
# duplicate mixins while preserving the accepted provider ordering.
_FINAL_PROVIDER_ORDER = (
    KreaImageEditBridgeMixin,
    DepthControlBridgeMixin,
    PoseControlBridgeMixin,
    ControlNetBridgeMixin,
)
_FINAL_ASYNC_FIELDS = ("asyncJob",)


class PowerShellBridge(
    KreaIdentityEditBridgeMixin,
    legacy.PowerShellBridge,
):
    """Final v0.3 bridge plus the pinned Krea Identity Edit provider layer."""

    def comfyui_runtime(self):
        return super().comfyui_runtime()


class StableAmdApi(
    KreaIdentityEditApiMixin,
    legacy.StableAmdApi,
):
    """Final v0.3 API plus Krea Identity Edit dependency management."""


base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
