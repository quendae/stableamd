import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER = REPO_ROOT / "app" / "backend" / "stableamd_v03_server.py"


class StableAmdV03IsolatedServerImportTests(unittest.TestCase):
    def test_v03_server_bootstraps_sibling_backend_module_under_isolated_python(self):
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

    def test_isolated_v03_server_exposes_upscale_route_without_test_import_side_effects(self):
        probe = f'''
import importlib.util
spec = importlib.util.spec_from_file_location("stableamd_v03_isolated", r"{SERVER}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Bridge:
    def upscale_models(self):
        return {{"root": "x", "models": ["RealESRGAN_x2plus.pth"]}}
api = module.StableAmdApi(Bridge())
status, payload = api.dispatch("GET", "/api/upscale-models")
print(status)
print(payload.get("models", []))
'''
        completed = subprocess.run(
            [sys.executable, "-I", "-c", probe],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertIn("200", completed.stdout)
        self.assertIn("RealESRGAN_x2plus.pth", completed.stdout)


if __name__ == "__main__":
    unittest.main()
