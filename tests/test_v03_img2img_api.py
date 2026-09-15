import base64
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import StableAmdApi


class Img2ImgBridge:
    def __init__(self):
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return {"PromptId": "img2img-1", "Mode": request.get("mode")}


class StableAmdV03Img2ImgApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Img2ImgBridge()
        self.api = StableAmdApi(self.bridge)
        self.png_data = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"stub").decode("ascii")

    def test_accepts_sdxl_img2img_product_contract(self):
        request = {
            "prompt": "watercolor cat",
            "modelId": "mdl_sdxl",
            "mode": "img2img",
            "denoise": 0.55,
            "inputImage": {
                "name": "cat.png",
                "mimeType": "image/png",
                "dataBase64": self.png_data,
            },
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["Mode"], "img2img")
        self.assertEqual(self.bridge.calls[-1], request)

    def test_rejects_missing_or_unsafe_img2img_input(self):
        invalid = [
            {"prompt": "x", "mode": "img2img", "denoise": 0.5},
            {"prompt": "x", "mode": "img2img", "denoise": -0.1, "inputImage": {"name": "x.png", "mimeType": "image/png", "dataBase64": self.png_data}},
            {"prompt": "x", "mode": "img2img", "denoise": 1.1, "inputImage": {"name": "x.png", "mimeType": "image/png", "dataBase64": self.png_data}},
            {"prompt": "x", "mode": "img2img", "denoise": 0.5, "inputImage": {"name": "x.exe", "mimeType": "application/octet-stream", "dataBase64": self.png_data}},
            {"prompt": "x", "mode": "img2img", "denoise": 0.5, "inputImage": {"name": "x.png", "mimeType": "image/png", "dataBase64": "%%%not-base64%%%"}},
            {"prompt": "x", "mode": "made-up"},
        ]
        for request in invalid:
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400, request)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)

    def test_txt2img_stays_backward_compatible_without_mode_or_input_image(self):
        request = {"prompt": "plain txt2img", "modelId": "mdl_sdxl"}
        status, _ = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.calls[-1], request)


if __name__ == "__main__":
    unittest.main()
