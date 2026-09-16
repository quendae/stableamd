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
            "FluxKontextMultiReferenceLatentMethod",
        }


class StableAmdV03KreaPoseAspectTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakePoseAspectBridge()

    def test_krea_compact_reference_preserves_staged_control_map_aspect(self):
        input_root = REPO_ROOT / ".runtime" / "stableamd" / "input"
        input_root.mkdir(parents=True, exist_ok=True)
        staged = input_root / "test-13M-Salute-OpenPoseFull.png"
        # The Krea path only needs the source dimensions here; write a minimal
        # PNG header carrying the real 13M_Salute OpenPoseFull dimensions.
        staged.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + (13).to_bytes(4, "big")
            + b"IHDR"
            + (1192).to_bytes(4, "big")
            + (2536).to_bytes(4, "big")
        )
        try:
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
            }
            context = {
                "image_name": staged.name,
                "width": 1024,
                "height": 1024,
                "strength": 1.0,
            }

            result = self.bridge._inject_krea_openpose(workflow, context)

            # 1192x2536 compacted to a 512 px long side, snapped to /16,
            # must remain portrait instead of being coerced to the 1:1 output frame.
            self.assertEqual(result["61"]["inputs"]["width"], 240)
            self.assertEqual(result["61"]["inputs"]["height"], 512)
        finally:
            staged.unlink(missing_ok=True)

    def test_frontend_keeps_krea_pose_map_aspect_instead_of_output_safe_frame(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-pose-safe-frame.js").read_text(encoding="utf-8")
        self.assertIn("requestModelFamily", source)
        self.assertIn("family !== 'krea2'", source)
        self.assertIn("shouldAutoFitOpenPosePayload", source)
        self.assertIn("fitOpenPosePayloadToFrame", source)


if __name__ == "__main__":
    unittest.main()
