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
from stableamd_v03_krea_identity_graph import KreaIdentityGraphBridgeMixin  # noqa: F401,E402
from stableamd_v03_character_sheet_v2 import (  # noqa: E402
    CharacterSheetV2ApiMixin,
    CharacterSheetV2BridgeMixin,
    KreaIdentityGenerationBridgeMixin,
)
from stableamd_v03_character_sheet_identity_tuning import (  # noqa: E402
    CharacterSheetV2IdentityTuningBridgeMixin,
)
from stableamd_v03_character_sheet_face_refine import (  # noqa: E402
    CharacterSheetV2FaceRefineBridgeMixin,
)
from stableamd_v03_character_sheet_face_guard import (  # noqa: E402
    CharacterSheetV2FacePanelGuardBridgeMixin,
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
# actual legacy instances are inherited once through legacy.PowerShellBridge;
# v2 layers ahead of them without duplicating the accepted provider mixins.
_FINAL_PROVIDER_ORDER = (
    KreaImageEditBridgeMixin,
    DepthControlBridgeMixin,
    PoseControlBridgeMixin,
    ControlNetBridgeMixin,
)
_FINAL_ASYNC_FIELDS = ("asyncJob",)


class PowerShellBridge(
    CharacterSheetV2FacePanelGuardBridgeMixin,
    CharacterSheetV2FaceRefineBridgeMixin,
    CharacterSheetV2IdentityTuningBridgeMixin,
    CharacterSheetV2BridgeMixin,
    KreaIdentityGenerationBridgeMixin,
    KreaIdentityGraphBridgeMixin,
    KreaIdentityEditBridgeMixin,
    legacy.PowerShellBridge,
):
    """Final v0.3 bridge with guarded two-stage Character Sheet v2 refinement."""

    def comfyui_runtime(self):
        return super().comfyui_runtime()


class StableAmdApi(
    CharacterSheetV2ApiMixin,
    KreaIdentityEditApiMixin,
    legacy.StableAmdApi,
):
    """Final v0.3 API with Character Sheet v2 and Krea Identity dependency management."""

    _generation_fields = set(legacy.StableAmdApi._generation_fields) | {
        "characterSheetVersion",
        "characterDescription",
        "characterSheetDetailer",
    }


base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
