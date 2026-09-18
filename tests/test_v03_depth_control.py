from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class FakeDepthBridge(server.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)

    def _zimage_fun_patch_name(self, required=False):
        return server.ZIMAGE_FUN_PATCH

    def _node_available(self, node_name: str) -> bool:
        return node_name in {"ModelPatchLoader", "ZImageFunControlnet"}


class StableAmdV03DepthControlTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeDepthBridge()

    def test_final_bridge_composes_depth_layer_before_pose_control(self):
        mro = [item.__name__ for item in server.PowerShellBridge.mro()]
        self.assertIn("DepthControlBridgeMixin", mro)
        self.assertLess(mro.index("DepthControlBridgeMixin"), mro.index("PoseControlBridgeMixin"))

    def test_depth_anything_small_safetensors_is_pinned(self):
        self.assertEqual(server.DEPTH_ANYTHING_MODEL_BYTES, 99173660)
        self.assertEqual(
            server.DEPTH_ANYTHING_MODEL_SHA256,
            "3152477ce0d8d6978d76b995120de97cb5b928701fd0f817769f59e249a16b70",
        )
        self.assertEqual(server.DEPTH_ANYTHING_LICENSE, "Apache-2.0")

    def test_control_dependencies_expose_installable_depth_preprocessor(self):
        payload = self.bridge.controlnet_dependencies()
        dependency = next(
            item for item in payload["dependencies"] if item.get("id") == "depth-anything-v2-small"
        )
        self.assertTrue(dependency["installable"])
        self.assertEqual(dependency["type"], "depth-preprocessor")
        self.assertEqual(dependency["model"]["sha256"], server.DEPTH_ANYTHING_MODEL_SHA256)

    def test_zimage_depth_graph_reuses_union_patch_without_canny(self):
        workflow = {
            "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3.0}},
            "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
            "3": {"class_type": "KSampler", "inputs": {"model": ["11", 0]}},
        }
        context = {
            "image_name": "depth.png",
            "width": 1024,
            "height": 1024,
            "strength": 1.0,
        }

        result = self.bridge._inject_zimage_depth(workflow, context)

        self.assertEqual(result["80"]["class_type"], "LoadImage")
        self.assertEqual(result["81"]["class_type"], "ImageScale")
        self.assertEqual(result["82"]["class_type"], "ModelPatchLoader")
        self.assertEqual(result["82"]["inputs"]["name"], server.ZIMAGE_FUN_PATCH)
        self.assertEqual(result["83"]["class_type"], "ZImageFunControlnet")
        self.assertEqual(result["83"]["inputs"]["image"], ["81", 0])
        self.assertEqual(result["11"]["inputs"]["model"], ["83", 0])
        self.assertNotIn("Canny", [node.get("class_type") for node in result.values()])

    def test_frontend_preprocesses_depth_source_and_exposes_preview(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-controlnet.js").read_text(encoding="utf-8")
        self.assertIn("/api/controlnet/preprocess/depth", source)
        self.assertIn("controlnet-depth-preview", source)
        self.assertIn("type === 'depth'", source)


if __name__ == "__main__":
    unittest.main()
