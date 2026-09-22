import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class StableAmdV03PowerShellModelDiscoveryTests(unittest.TestCase):
    def test_model_discovery_returns_machine_readable_payload_through_pwsh(self):
        pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is not installed on this runner")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "config").mkdir()

            # Reuse the repository scripts/config while keeping generated
            # registries/runtime state isolated from the checkout.
            for name in (
                "List-Models.ps1",
                "List-BundleModels.ps1",
                "StableAmd.Runtime.psm1",
                "StableAmd.Models.psm1",
                "StableAmd.ModelFamilies.psm1",
                "StableAmd.BundleRoots.psm1",
                "StableAmd.Bundles.psm1",
                "StableAmd.TemplateBundles.psm1",
            ):
                shutil.copy2(REPO_ROOT / "scripts" / name, root / "scripts" / name)
            shutil.copy2(REPO_ROOT / "config" / "stableamd.default.json", root / "config" / "stableamd.default.json")

            bridge = server.PowerShellBridge(root, powershell=pwsh)
            models = bridge.models()

        self.assertIsInstance(models, list)
        families = {str(item.get("family") or "") for item in models if isinstance(item, dict)}
        self.assertIn("z-image-turbo", families)
        self.assertIn("krea2", families)


if __name__ == "__main__":
    unittest.main()
