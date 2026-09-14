import base64
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_v03_lora_server import StableAmdApi


class OutpaintBridge:
    def __init__(self):
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return {"PromptId": "outpaint-1", "Mode": "outpaint"}


class StableAmdV03OutpaintContextTests(unittest.TestCase):
    def setUp(self):
        self.bridge = OutpaintBridge()
        self.api = StableAmdApi(self.bridge)
        self.png_data = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"stub").decode("ascii")

    def request(self):
        return {
            "prompt": "extend the forest beyond the original frame",
            "modelId": "mdl_sdxl",
            "mode": "inpaint",
            "denoise": 0.8,
            "inputImage": {
                "name": "stableamd-outpaint.png",
                "mimeType": "image/png",
                "dataBase64": self.png_data,
            },
            "editContext": {
                "kind": "outpaint",
                "sourcePromptId": "source-123",
                "sourceImagePath": "C:/StableAMD/output/source.png",
                "margins": {"left": 256, "right": 128, "top": 0, "bottom": 64},
            },
        }

    def test_accepts_outpaint_edit_context_on_inpaint_transport(self):
        request = self.request()
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["Mode"], "outpaint")
        self.assertEqual(self.bridge.calls[-1], request)

    def test_rejects_invalid_outpaint_context(self):
        invalid_contexts = [
            {"kind": "outpaint", "margins": {"left": 0, "right": 0, "top": 0, "bottom": 0}},
            {"kind": "outpaint", "margins": {"left": 7, "right": 0, "top": 0, "bottom": 0}},
            {"kind": "outpaint", "margins": {"left": 2048, "right": 0, "top": 0, "bottom": 0}},
            {"kind": "other", "margins": {"left": 64, "right": 0, "top": 0, "bottom": 0}},
        ]
        for context in invalid_contexts:
            request = self.request()
            request["editContext"] = context
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400, context)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)

    def test_rejects_edit_context_outside_inpaint_transport(self):
        request = self.request()
        request["mode"] = "txt2img"
        request.pop("inputImage", None)
        request.pop("denoise", None)
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 400)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
