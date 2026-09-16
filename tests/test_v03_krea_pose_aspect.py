from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class FakePoseAspectBridge(server.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)

    def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
        return f"krea/{filename}"

    def _node_available(self, node_name: str) -> bool:
        return node_name in {
            "TextEncodeKrea2OstrisEdit",
            "Krea2OstrisEditModelPatch",
            "LoraLoaderModelOnly",
            "FluxKontextImageScale",
            "FluxKontextMultiReferenceLatentMethod",
            "SelectVAEDevice",
        }


class StableAmdV03KreaPoseAspectTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakePoseAspectBridge()

    def test_krea_uses_official_kontext_reference_scaler(self):
        workflow = {
            "10": {"class_type": "UNETLoader", "inputs": {}},
            "11": {"class_type": "CLIPLoader", "inputs": {}},
            "12": {"class_type": "VAELoader", "inputs": {}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "saluting man", "clip": ["11", 0]}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"model": ["10", 0], "positive": ["6", 0], "negative": ["13", 0], "latent_image": ["5", 0]},
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        }
        context = {
            "image_name": "13M_Salute-OpenPoseFull-safe-frame.png",
            "width": 1024,
            "height": 1024,
            "strength": 1.0,
        }

        result = self.bridge._inject_krea_openpose(workflow, context)

        self.assertEqual(result["61"]["class_type"], "FluxKontextImageScale")
        self.assertEqual(result["61"]["inputs"], {"image": ["60", 0]})
        self.assertEqual(result["5"]["inputs"]["width"], 1024)
        self.assertEqual(result["5"]["inputs"]["height"], 1024)
        self.assertEqual(result["68"]["class_type"], "SelectVAEDevice")
        self.assertEqual(result["68"]["inputs"]["device"], "gpu:0")
        self.assertEqual(result["8"]["inputs"]["vae"], ["68", 0])

    def test_frontend_safe_frames_krea_templates_to_selected_output_aspect(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-pose-safe-frame.js").read_text(encoding="utf-8")
        self.assertIn("shouldAutoFitOpenPosePayload", source)
        self.assertIn("fitOpenPosePayloadToFrame", source)
        self.assertNotIn("family !== 'krea2'", source)


if __name__ == "__main__":
    unittest.main()
