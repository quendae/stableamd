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
        return node_name in {
            "ModelPatchLoader",
            "ZImageFunControlnet",
            "Canny",
            "TextEncodeKrea2OstrisEdit",
            "Krea2OstrisEditModelPatch",
            "LoraLoaderModelOnly",
            "FluxKontextImageScale",
            "FluxKontextMultiReferenceLatentMethod",
        }

    def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
        return f"krea/{filename}"


class StableAmdV03PoseControlTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakePoseBridge()

    @staticmethod
    def _krea_workflow(cfg: float = 1.0):
        return {
            "10": {"class_type": "UNETLoader", "inputs": {}},
            "11": {"class_type": "CLIPLoader", "inputs": {}},
            "12": {"class_type": "VAELoader", "inputs": {}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "man in a suit", "clip": ["11", 0]}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["10", 0],
                    "positive": ["6", 0],
                    "negative": ["13", 0],
                    "latent_image": ["5", 0],
                    "cfg": cfg,
                },
            },
        }

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

    def test_krea_openpose_uses_official_reference_scaler_and_training_semantics(self):
        workflow = self._krea_workflow(cfg=1.0)
        context = {
            "image_name": "pose.png",
            "width": 1024,
            "height": 1024,
            "strength": 1.0,
        }

        result = self.bridge._inject_krea_openpose(workflow, context)

        self.assertEqual(result["61"]["class_type"], "FluxKontextImageScale")
        self.assertEqual(result["61"]["inputs"], {"image": ["60", 0]})
        self.assertEqual(result["5"]["inputs"]["width"], 1024)
        self.assertEqual(result["5"]["inputs"]["height"], 1024)
        self.assertEqual(result["62"]["class_type"], "Krea2OstrisEditModelPatch")
        self.assertIs(result["62"]["inputs"]["kv_cache"], True)
        self.assertEqual(result["63"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(result["63"]["inputs"]["lora_name"], f"krea/{server.KREA_OPENPOSE_LORA}")
        self.assertEqual(result["64"]["inputs"]["image1"], ["61", 0])
        self.assertEqual(result["64"]["inputs"]["vae"], ["12", 0])
        self.assertNotIn("image1", result["65"]["inputs"])
        self.assertNotIn("vae", result["65"]["inputs"])
        self.assertEqual(result["66"]["class_type"], "FluxKontextMultiReferenceLatentMethod")
        self.assertEqual(result["66"]["inputs"]["conditioning"], ["64", 0])
        self.assertEqual(result["66"]["inputs"]["reference_latents_method"], "index_timestep_zero")
        self.assertEqual(result["67"]["class_type"], "FluxKontextMultiReferenceLatentMethod")
        self.assertEqual(result["67"]["inputs"]["conditioning"], ["65", 0])
        self.assertEqual(result["3"]["inputs"]["positive"], ["66", 0])
        self.assertEqual(result["3"]["inputs"]["negative"], ["67", 0])

    def test_krea_cfg_above_one_keeps_negative_reference_conditioning(self):
        workflow = self._krea_workflow(cfg=1.5)
        context = {
            "image_name": "pose.png",
            "width": 1024,
            "height": 1024,
            "strength": 1.0,
        }

        result = self.bridge._inject_krea_openpose(workflow, context)

        self.assertEqual(result["65"]["inputs"]["image1"], ["61", 0])
        self.assertEqual(result["65"]["inputs"]["vae"], ["12", 0])

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
