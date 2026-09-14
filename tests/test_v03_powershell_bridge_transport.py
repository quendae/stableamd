import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class StableAmdV03PowerShellTransportTests(unittest.TestCase):
    def test_prefers_pwsh7_when_bridge_chooses_powershell_automatically(self):
        def which(name):
            mapping = {
                "powershell.exe": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "pwsh.exe": r"C:\Program Files\PowerShell\7\pwsh.exe",
            }
            return mapping.get(name)

        with patch.object(server.shutil, "which", side_effect=which):
            bridge = server.PowerShellBridge(REPO_ROOT)

        self.assertEqual(bridge.powershell, r"C:\Program Files\PowerShell\7\pwsh.exe")

    def test_sentinel_json_survives_warning_noise(self):
        payload = server.PowerShellBridge._parse_powershell_json(
            "WARNING: module emitted host output\n"
            "progress 50%\n"
            '__STABLEAMD_JSON__{"models":[{"id":"krea"}],"count":1}\n'
        )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["models"][0]["id"], "krea")

    def test_run_script_uses_sentinel_envelope(self):
        bridge = server.PowerShellBridge(REPO_ROOT, powershell="pwsh.exe")
        completed = SimpleNamespace(
            returncode=0,
            stdout='host noise\n__STABLEAMD_JSON__{"models":[],"count":0}\n',
            stderr="",
        )

        with patch.object(server.subprocess, "run", return_value=completed) as run:
            result = bridge._run_script("List-Models.ps1")

        self.assertEqual(result, {"models": [], "count": 0})
        command = run.call_args.args[0][-1]
        self.assertIn("__STABLEAMD_JSON__", command)
        self.assertIn("$ErrorActionPreference = 'Stop'", command)

    def test_unparseable_success_names_script_and_includes_output_tail(self):
        bridge = server.PowerShellBridge(REPO_ROOT, powershell="pwsh.exe")
        completed = SimpleNamespace(
            returncode=0,
            stdout="unexpected host-only output",
            stderr="",
        )

        with patch.object(server.subprocess, "run", return_value=completed):
            with self.assertRaises(server.base.StableAmdBridgeError) as captured:
                bridge._run_script("List-BundleModels.ps1")

        message = str(captured.exception)
        self.assertIn("List-BundleModels.ps1", message)
        self.assertIn("pwsh.exe", message)
        self.assertIn("unexpected host-only output", message)


if __name__ == "__main__":
    unittest.main()
