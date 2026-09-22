import base64
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_v03_server import StableAmdApi


class InpaintBridge:
    def __init__(self):
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return {"PromptId": "inpaint-1", "Mode": request.get("mode")}


class StableAmdV03InpaintApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = InpaintBridge()
        self.api = StableAmdApi(self.bridge)
        self.png_data = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"stub").decode("ascii")

    def test_accepts_inpaint_with_embedded_alpha_mask(self):
        request = {
            "prompt": "replace the painted region with red fabric",
            "modelId": "mdl_sdxl",
            "mode": "inpaint",
            "denoise": 0.8,
            "inputImage": {
                "name": "StableAMD_inpaint.png",
                "mimeType": "image/png",
                "dataBase64": self.png_data,
            },
            "loraStack": [
                {"name": "detail.safetensors", "modelStrength": 0.8, "clipStrength": 0.7, "enabled": True}
            ],
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["Mode"], "inpaint")
        self.assertEqual(self.bridge.calls[-1], request)

    def test_rejects_inpaint_without_png_input_or_valid_denoise(self):
        invalid = [
            {"prompt": "x", "mode": "inpaint", "denoise": 0.8},
            {"prompt": "x", "mode": "inpaint", "denoise": -0.1, "inputImage": {"name": "x.png", "mimeType": "image/png", "dataBase64": self.png_data}},
            {"prompt": "x", "mode": "inpaint", "denoise": 1.1, "inputImage": {"name": "x.png", "mimeType": "image/png", "dataBase64": self.png_data}},
            {"prompt": "x", "mode": "inpaint", "denoise": 0.8, "inputImage": {"name": "x.jpg", "mimeType": "image/jpeg", "dataBase64": base64.b64encode(b"\xff\xd8\xffstub").decode("ascii")}},
        ]
        for request in invalid:
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400, request)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)


if __name__ == "__main__":
    unittest.main()
