import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import PowerShellBridge


class PowerShellBridgeIntegrationTests(unittest.TestCase):
    def test_empty_service_result_with_host_output_is_treated_as_no_result(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell is required for this integration test")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            scripts_root = repo_root / "scripts"
            scripts_root.mkdir(parents=True)
            (scripts_root / "List-Models.ps1").write_text(
                "param([string]$RepoRoot)\nWrite-Host 'synthetic service chatter'\nreturn @()\n",
                encoding="utf-8",
            )

            bridge = PowerShellBridge(repo_root=repo_root, powershell=powershell)
            self.assertEqual(bridge.models(), [])


if __name__ == "__main__":
    unittest.main()
