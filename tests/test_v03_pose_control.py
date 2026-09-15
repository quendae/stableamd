from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class FakePoseBridge(server.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)

    def _zimage_fun_patch_name(self, required=False):
        return server.ZIMAGE_FUN_PATCH

    def _node_available(self, node_name: str) -> bool:
        return node_name in {"ModelPatchLoader", "ZImageFunControlnet", "Canny"}


class StableAmdV03PoseControlTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakePoseBridge()

    def test_zimage_openpose_graph_uses_union_patch_without_canny_preprocessor(self):
        workflow = {
            "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3.0}},
            "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
            "3": {"class_type": "KSampler", "inputs": {"model": ["11", 0]}},
        }
        context = {
            "image_name": "pose.png",
            "width": 1024,
            "height": 1024,
            "strength": 0.9,
        }

        result = self.bridge._inject_zimage_openpose(workflow, context)

        self.assertEqual(result["70"]["class_type"], "LoadImage")
        self.assertEqual(result["71"]["class_type"], "ImageScale")
        self.assertEqual(result["71"]["inputs"]["upscale_method"], "nearest-exact")
        self.assertEqual(result["72"]["class_type"], "ModelPatchLoader")
        self.assertEqual(result["72"]["inputs"]["name"], server.ZIMAGE_FUN_PATCH)
        self.assertEqual(result["73"]["class_type"], "ZImageFunControlnet")
        self.assertEqual(result["73"]["inputs"]["image"], ["71", 0])
        self.assertEqual(result["11"]["inputs"]["model"], ["73", 0])
        self.assertNotIn("Canny", [node.get("class_type") for node in result.values()])

    def test_zimage_model_support_exposes_openpose_when_union_route_is_ready(self):
        support = {
            "models": [
                {
                    "id": "z",
                    "family": "z-image-turbo",
                    "capabilities": {"controlnet": "supported"},
                    "controlPolicy": {
                        "controls": [
                            {
                                "id": "canny",
                                "label": "Canny edges",
                                "status": "supported",
                            }
                        ]
                    },
                }
            ]
        }

        class SupportParent:
            def model_support(inner_self):
                return support

        class TestMixin(server.PoseControlBridgeMixin, SupportParent):
            def _zimage_pose_ready(inner_self):
                return True

        result = TestMixin().model_support()
        controls = result["models"][0]["controlPolicy"]["controls"]
        openpose = next(item for item in controls if item["id"] == "openpose")
        self.assertEqual(openpose["status"], "supported")
        self.assertEqual(openpose["preprocessor"], "precomputed-or-editor")

    def test_final_bridge_composes_pose_layer_before_controlnet(self):
        mro = [item.__name__ for item in server.PowerShellBridge.mro()]
        self.assertLess(mro.index("PoseControlBridgeMixin"), mro.index("ControlNetBridgeMixin"))


if __name__ == "__main__":
    unittest.main()
