import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_server as v03


CHECKPOINT = {
    "id": "mdl_sdxl",
    "name": "sd_xl_base_1.0.safetensors",
    "family": "sdxl",
    "assetMode": "checkpoint",
    "path": str(REPO_ROOT / "fake-sdxl.safetensors"),
}

ZIMAGE = {
    "id": "bnd_zimage",
    "name": "Z-Image Turbo",
    "family": "z-image-turbo",
    "provider": "z-image-turbo-bundle",
    "assetMode": "bundle",
    "assets": {
        "diffusion_model": [str(REPO_ROOT / "z_image_turbo_bf16.safetensors")],
        "text_encoder": [str(REPO_ROOT / "qwen_3_4b.safetensors")],
        "vae": [str(REPO_ROOT / "ae.safetensors")],
    },
}


class FakeBridge(v03.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)
        self.calls = []
        self.zimage_requests = []

    def _run_script(self, name, parameters=None):
        self.calls.append((name, parameters or []))
        if name == "List-Models.ps1":
            return {"models": [CHECKPOINT]}
        if name == "List-BundleModels.ps1":
            return {"models": [ZIMAGE]}
        if name == "Invoke-Txt2Img.ps1":
            return {"PromptId": "checkpoint-path"}
        return None

    def _generate_zimage_turbo(self, request, model):
        self.zimage_requests.append((request, model))
        return {"PromptId": "zimage-path", "ModelId": model["id"]}


class StableAmdV03ZImageBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()

    def test_models_merge_checkpoint_and_template_bundle_models(self):
        models = self.bridge.models()
        self.assertEqual([model["id"] for model in models], ["mdl_sdxl", "bnd_zimage"])
        self.assertIn(("List-BundleModels.ps1", []), self.bridge.calls)

    def test_txt2img_routes_selected_zimage_bundle_to_zimage_provider(self):
        request = {"prompt": "a glass lighthouse", "modelId": "bnd_zimage"}
        result = self.bridge.generate(request)
        self.assertEqual(result["PromptId"], "zimage-path")
        self.assertEqual(result["ModelId"], "bnd_zimage")
        self.assertEqual(len(self.bridge.zimage_requests), 1)
        self.assertEqual(self.bridge.zimage_requests[0][1]["family"], "z-image-turbo")
        self.assertFalse(any(name == "Invoke-Txt2Img.ps1" for name, _ in self.bridge.calls))

    def test_checkpoint_generation_still_uses_existing_product_command(self):
        request = {"prompt": "a red plane", "modelId": "mdl_sdxl"}
        result = self.bridge.generate(request)
        self.assertEqual(result["PromptId"], "checkpoint-path")
        self.assertTrue(any(name == "Invoke-Txt2Img.ps1" for name, _ in self.bridge.calls))


if __name__ == "__main__":
    unittest.main()
