import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER = REPO_ROOT / "app" / "backend" / "stableamd_server.py"


class StableAmdIsolatedServerImportTests(unittest.TestCase):
    def test_server_starts_import_phase_under_isolated_python(self):
        completed = subprocess.run(
            [sys.executable, "-I", str(SERVER), "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertIn("StableAMD", completed.stdout)


if __name__ == "__main__":
    unittest.main()
