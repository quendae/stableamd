import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_server as v03
import upscale_support


class UpscaleApiBridge:
    def __init__(self):
        self.requests = []

    def upscale_models(self):
        return {
            "root": "C:/stableamd/upscale_models",
            "models": ["4x-UltraSharp.pth", "RealESRGAN_x2plus.pth"],
        }

    def upscale(self, request):
        self.requests.append(request)
        return {
            "PromptId": "upscale-ok",
            "ImagePath": "C:/stableamd/output/upscaled.png",
            "UpscaleModel": request["modelName"],
        }


class StableAmdV03UpscaleApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = UpscaleApiBridge()
        self.api = v03.StableAmdApi(self.bridge)

    def test_lists_upscale_models(self):
        status, payload = self.api.dispatch("GET", "/api/upscale-models")
        self.assertEqual(status, 200)
        self.assertIn("4x-UltraSharp.pth", payload["models"])

    def test_accepts_managed_output_path_and_model_name(self):
        request = {"imagePath": "C:/stableamd/output/source.png", "modelName": "4x-UltraSharp.pth"}
        status, payload = self.api.dispatch("POST", "/api/upscale", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["UpscaleModel"], "4x-UltraSharp.pth")
        self.assertEqual(self.bridge.requests, [request])

    def test_rejects_missing_fields_and_unknown_upscale_fields(self):
        status, payload = self.api.dispatch("POST", "/api/upscale", b"{}")
        self.assertEqual(status, 400)
        self.assertIn("imagePath", payload["error"])

        status, payload = self.api.dispatch(
            "POST",
            "/api/upscale",
            json.dumps({"imagePath": "source.png", "modelName": "x.pth", "workflow": {}}).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("Unsupported upscale field", payload["error"])

    def test_reads_current_comfy_upscale_combo_options_contract(self):
        payload = {
            "UpscaleModelLoader": {
                "input": {
                    "required": {
                        "model_name": [
                            "COMBO",
                            {
                                "multiselect": False,
                                "options": ["RealESRGAN_x2plus.pth"],
                            },
                        ],
                    }
                }
            }
        }
        bridge = upscale_support.UpscalePowerShellBridge(REPO_ROOT, powershell=sys.executable)
        bridge._comfy_json = lambda _: payload

        self.assertEqual(bridge._upscale_choices(), ["RealESRGAN_x2plus.pth"])

    def test_reports_model_on_disk_when_comfy_has_not_registered_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            root = repo_root / ".runtime" / "stableamd" / "models" / "upscale_models"
            root.mkdir(parents=True)
            (root / "RealESRGAN_x2plus.pth").write_bytes(b"placeholder")

            bridge = upscale_support.UpscalePowerShellBridge(repo_root, powershell=sys.executable)
            bridge._upscale_choices = lambda: []

            payload = bridge.upscale_models()

            self.assertEqual(payload["models"], [])
            self.assertEqual(payload["diskModels"], ["RealESRGAN_x2plus.pth"])
            self.assertTrue(payload["restartRecommended"])


if __name__ == "__main__":
    unittest.main()
