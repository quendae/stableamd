from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
FRONTEND_ROOT = REPO_ROOT / "app" / "frontend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class RuntimeBridge:
    def comfyui_runtime(self):
        return {
            "backendUrl": "http://127.0.0.1:8190/",
            "installed": {"version": "0.35.0", "commit": "abc123"},
            "pinned": {"version": "0.35.0", "commit": "abc123"},
            "latest": {"version": "0.36.0", "tag": "v0.36.0"},
            "updateAvailable": True,
            "pinMatchesCheckout": True,
        }


class StableAmdComfyUiRuntimeTests(unittest.TestCase):
    def test_final_api_exposes_comfyui_runtime_status(self):
        api = server.StableAmdApi(RuntimeBridge())
        status, payload = api.dispatch("GET", "/api/comfyui-runtime")
        self.assertEqual(status, 200)
        self.assertEqual(payload["backendUrl"], "http://127.0.0.1:8190/")
        self.assertEqual(payload["installed"]["version"], "0.35.0")
        self.assertTrue(payload["updateAvailable"])

    def test_main_navigation_exposes_open_comfyui_and_loads_runtime_controller(self):
        source = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="open-comfyui"', source)
        self.assertIn("Open ComfyUI", source)
        self.assertIn('src="/app-comfy-runtime.js"', source)

    def test_runtime_controller_renders_diagnostics_and_updates_open_link(self):
        source = (FRONTEND_ROOT / "app-comfy-runtime.js").read_text(encoding="utf-8")
        self.assertIn('/api/comfyui-runtime', source)
        self.assertIn('open-comfyui', source)
        self.assertIn('comfyui-runtime-card', source)
        self.assertIn('updateAvailable', source)
        self.assertIn('pinMatchesCheckout', source)

    def test_runtime_bridge_has_pinned_release_check_without_auto_update(self):
        source = (BACKEND_ROOT / "stableamd_v03_edit_server.py").read_text(encoding="utf-8")
        self.assertIn("COMFYUI_RELEASES_URL", source)
        self.assertIn("def comfyui_runtime", source)
        self.assertNotIn("git pull", source.lower())


if __name__ == "__main__":
    unittest.main()
