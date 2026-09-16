from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class FakeControlBridge(server.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)

    def _zimage_fun_patch_name(self, required=False):
        return server.ZIMAGE_FUN_PATCH

    def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
        return f"krea/{filename}"

    def _node_available(self, node_name: str) -> bool:
        return node_name in {
            "Canny",
            "ModelPatchLoader",
            "ZImageFunControlnet",
            "TextEncodeKrea2OstrisEdit",
            "Krea2OstrisEditModelPatch",
            "LoraLoaderModelOnly",
            "FluxKontextImageScale",
            "FluxKontextMultiReferenceLatentMethod",
        }


class StableAmdV03ControlNetTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeControlBridge()

    def test_final_api_accepts_control_generation_field(self):
        self.assertIn("control", server.StableAmdApi._generation_fields)
        api = server.StableAmdApi(self.bridge)
        tiny_png = base64.b64encode(b"\x89PNG\r\n\x1a\ncontrol").decode("ascii")
        request = {
            "prompt": "controlled image",
            "control": {
                "type": "canny",
                "strength": 1.0,
                "cannyLow": 0.4,
                "cannyHigh": 0.8,
                "image": {"name": "control.png", "mimeType": "image/png", "dataBase64": tiny_png},
            },
        }
        validated = api._validate_generation(request)
        self.assertEqual(validated["control"]["type"], "canny")

    def test_zimage_canny_graph_uses_union_patch_and_core_canny(self):
        workflow = {
            "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3.0}},
            "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
            "3": {"class_type": "KSampler", "inputs": {"model": ["11", 0]}},
        }
        context = {
            "image_name": "control.png",
            "width": 1024,
            "height": 1024,
            "strength": 0.9,
            "canny_low": 0.3,
            "canny_high": 0.7,
        }
        result = self.bridge._inject_zimage_canny(workflow, context)
        self.assertEqual(result["62"]["class_type"], "Canny")
        self.assertEqual(result["63"]["class_type"], "ModelPatchLoader")
        self.assertEqual(result["63"]["inputs"]["name"], server.ZIMAGE_FUN_PATCH)
        self.assertEqual(result["64"]["class_type"], "ZImageFunControlnet")
        self.assertEqual(result["64"]["inputs"]["image"], ["62", 0])
        self.assertEqual(result["11"]["inputs"]["model"], ["64", 0])

    def test_krea_openpose_graph_uses_trained_isolated_reference_path(self):
        workflow = {
            "10": {"class_type": "UNETLoader", "inputs": {}},
            "11": {"class_type": "CLIPLoader", "inputs": {}},
            "12": {"class_type": "VAELoader", "inputs": {}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "astronaut", "clip": ["11", 0]}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"model": ["10", 0], "positive": ["6", 0], "negative": ["13", 0], "latent_image": ["5", 0]},
            },
        }
        context = {"image_name": "pose.png", "width": 1024, "height": 1024, "strength": 0.85}
        result = self.bridge._inject_krea_openpose(workflow, context)
        self.assertEqual(result["61"]["class_type"], "FluxKontextImageScale")
        self.assertEqual(result["61"]["inputs"], {"image": ["60", 0]})
        self.assertEqual(result["62"]["class_type"], "Krea2OstrisEditModelPatch")
        self.assertIs(result["62"]["inputs"]["kv_cache"], True)
        self.assertEqual(result["63"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(result["63"]["inputs"]["lora_name"], f"krea/{server.KREA_OPENPOSE_LORA}")
        self.assertEqual(result["64"]["class_type"], "TextEncodeKrea2OstrisEdit")
        self.assertEqual(result["64"]["inputs"]["image1"], ["61", 0])
        self.assertEqual(result["66"]["class_type"], "FluxKontextMultiReferenceLatentMethod")
        self.assertEqual(result["66"]["inputs"]["reference_latents_method"], "index_timestep_zero")
        self.assertEqual(result["67"]["class_type"], "FluxKontextMultiReferenceLatentMethod")
        self.assertEqual(result["67"]["inputs"]["reference_latents_method"], "index_timestep_zero")
        self.assertEqual(result["3"]["inputs"]["model"], ["63", 0])
        self.assertEqual(result["3"]["inputs"]["positive"], ["66", 0])
        self.assertEqual(result["3"]["inputs"]["negative"], ["67", 0])

    def test_krea_openpose_dependencies_are_pinned(self):
        self.assertEqual(server.KREA_OPENPOSE_PLUGIN_COMMIT, "7756566160c4a1b24bb1bd9f0ff3ced1a83d7547")
        self.assertEqual(server.KREA_OPENPOSE_LORA_BYTES, 228587504)
        self.assertEqual(
            server.KREA_OPENPOSE_LORA_SHA256,
            "0ddc3aafce4abdf7af3309b2f00c1bacdf15df1f2b4fb7adc9ff71795da90ecf",
        )


if __name__ == "__main__":
    unittest.main()
