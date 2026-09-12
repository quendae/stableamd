import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import StableAmdApi


class BundleRootBridge:
    def __init__(self):
        self.calls = []

    def bundle_roots(self):
        self.calls.append(("bundle_roots", None))
        return {
            "diffusion_model": [{"role": "diffusion_model", "path": r"C:\AI\diffusion_models", "managed": False}],
            "text_encoder": [],
            "vae": [],
        }

    def browse_bundle_root(self, role):
        self.calls.append(("browse_bundle_root", role))
        return {"cancelled": False, "role": role, "path": r"D:\AI"}

    def add_bundle_root(self, role, path):
        self.calls.append(("add_bundle_root", (role, path)))
        return {"added": True, "role": role, "path": path, "restartRequired": True}

    def remove_bundle_root(self, role, path):
        self.calls.append(("remove_bundle_root", (role, path)))
        return {"removed": True, "role": role, "path": path, "restartRequired": True}


class StableAmdV03BundleRootApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = BundleRootBridge()
        self.api = StableAmdApi(self.bridge)

    def test_lists_all_bundle_asset_roots(self):
        status, payload = self.api.dispatch("GET", "/api/bundle-roots")
        self.assertEqual(status, 200)
        self.assertIn("diffusion_model", payload)
        self.assertEqual(payload["diffusion_model"][0]["path"], r"C:\AI\diffusion_models")
        self.assertEqual(self.bridge.calls, [("bundle_roots", None)])

    def test_browse_add_and_remove_are_role_scoped(self):
        browse = {"role": "text_encoder"}
        status, payload = self.api.dispatch("POST", "/api/bundle-roots/browse", json.dumps(browse).encode())
        self.assertEqual(status, 200)
        self.assertEqual(payload["role"], "text_encoder")

        request = {"role": "diffusion_model", "path": r"D:\FLUX"}
        status, payload = self.api.dispatch("POST", "/api/bundle-roots", json.dumps(request).encode())
        self.assertEqual(status, 200)
        self.assertTrue(payload["added"])

        status, payload = self.api.dispatch("POST", "/api/bundle-roots/remove", json.dumps(request).encode())
        self.assertEqual(status, 200)
        self.assertTrue(payload["removed"])

        self.assertIn(("browse_bundle_root", "text_encoder"), self.bridge.calls)
        self.assertIn(("add_bundle_root", ("diffusion_model", r"D:\FLUX")), self.bridge.calls)
        self.assertIn(("remove_bundle_root", ("diffusion_model", r"D:\FLUX")), self.bridge.calls)

    def test_rejects_unknown_roles_missing_paths_and_extra_fields(self):
        requests = [
            ("/api/bundle-roots/browse", {"role": "checkpoint"}),
            ("/api/bundle-roots", {"role": "diffusion_model"}),
            ("/api/bundle-roots", {"role": "vae", "path": r"D:\VAE", "command": "whoami"}),
            ("/api/bundle-roots/remove", {"role": "text_encoder", "path": "   "}),
        ]
        for target, request in requests:
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", target, json.dumps(request).encode())
            self.assertEqual(status, 400, request)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)


if __name__ == "__main__":
    unittest.main()
