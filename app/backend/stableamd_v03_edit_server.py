from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_v03_edit_server_legacy import *  # noqa: F401,F403,E402
import stableamd_v03_edit_server_legacy as legacy  # noqa: E402
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


class PowerShellBridge(
    KreaIdentityEditBridgeMixin,
    legacy.PowerShellBridge,
):
    """Final v0.3 bridge plus the pinned Krea Identity Edit provider layer."""


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
