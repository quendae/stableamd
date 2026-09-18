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
        return node_name in {
            "ModelPatchLoader",
            "ZImageFunControlnet",
            "Krea2ControlLoRALoader",
            "Krea2ControlImageEncode",
            "Krea2ControlApply",
        }

    def _lora_choice_by_leaf(self, filename: str, node_name: str = "LoraLoaderModelOnly"):
        if filename == "depth-control-lora.safetensors" and node_name == "Krea2ControlLoRALoader":
            return "krea/depth-control-lora.safetensors"
        return super()._lora_choice_by_leaf(filename, node_name)


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

    def test_krea_depth_plugin_and_control_lora_are_pinned(self):
        self.assertEqual(server.KREA_DEPTH_PLUGIN_REPOSITORY, "https://github.com/facok/comfyui-krea2-controlnet.git")
        self.assertEqual(server.KREA_DEPTH_PLUGIN_COMMIT, "79ebfd3bd80d2180b334dd7ce57f3c9ddaa0848f")
        self.assertEqual(server.KREA_DEPTH_LORA_FILENAME, "depth-control-lora.safetensors")
        self.assertEqual(server.KREA_DEPTH_LORA_BYTES, 861995928)
        self.assertEqual(
            server.KREA_DEPTH_LORA_SHA256,
            "fb80547ed79b47c1e3fea7bb9d36297e3917b2115fab6700ca1501350f9f483c",
        )
        self.assertEqual(server.KREA_DEPTH_LORA_LICENSE, "krea-2-community-license")

    def test_control_dependencies_expose_installable_depth_preprocessor(self):
        payload = self.bridge.controlnet_dependencies()
        dependency = next(
            item for item in payload["dependencies"] if item.get("id") == "depth-anything-v2-small"
        )
        self.assertTrue(dependency["installable"])
        self.assertEqual(dependency["type"], "depth-preprocessor")
        self.assertEqual(dependency["model"]["sha256"], server.DEPTH_ANYTHING_MODEL_SHA256)

    def test_control_dependencies_expose_installable_krea_depth_route(self):
        payload = self.bridge.controlnet_dependencies()
        dependency = next(item for item in payload["dependencies"] if item.get("id") == "krea2-depth")
        self.assertTrue(dependency["installable"])
        self.assertEqual(dependency["family"], "krea2")
        self.assertEqual(dependency["type"], "depth")
        self.assertEqual(dependency["plugin"]["commit"], server.KREA_DEPTH_PLUGIN_COMMIT)
        self.assertEqual(dependency["model"]["sha256"], server.KREA_DEPTH_LORA_SHA256)

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

    def test_krea_depth_graph_uses_native_control_lora_nodes(self):
        workflow = {
            "10": {"class_type": "UNETLoader", "inputs": {}},
            "12": {"class_type": "VAELoader", "inputs": {}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
            "3": {"class_type": "KSampler", "inputs": {"model": ["10", 0], "latent_image": ["5", 0]}},
        }
        context = {
            "image_name": "depth.png",
            "strength": 0.85,
            "lora_name": "krea/depth-control-lora.safetensors",
        }

        result = self.bridge._inject_krea_depth(workflow, context)

        self.assertEqual(result["90"]["class_type"], "LoadImage")
        self.assertEqual(result["91"]["class_type"], "Krea2ControlImageEncode")
        self.assertEqual(result["91"]["inputs"]["control_image"], ["90", 0])
        self.assertEqual(result["91"]["inputs"]["vae"], ["12", 0])
        self.assertEqual(result["91"]["inputs"]["latent"], ["5", 0])
        self.assertEqual(result["91"]["inputs"]["channel_mode"], "grayscale")
        self.assertEqual(result["91"]["inputs"]["normalize"], "per_image_minmax")
        self.assertIs(result["91"]["inputs"]["invert"], False)
        self.assertEqual(result["92"]["class_type"], "Krea2ControlLoRALoader")
        self.assertEqual(result["92"]["inputs"]["lora_name"], "krea/depth-control-lora.safetensors")
        self.assertEqual(result["92"]["inputs"]["strength"], 0.85)
        self.assertEqual(result["93"]["class_type"], "Krea2ControlApply")
        self.assertEqual(result["93"]["inputs"]["control_latent"], ["91", 0])
        self.assertEqual(result["3"]["inputs"]["model"], ["93", 0])

    def test_krea_model_support_exposes_depth_when_native_route_is_ready(self):
        class Parent:
            def model_support(inner_self):
                return {
                    "models": [
                        {
                            "id": "krea",
                            "family": "krea2",
                            "capabilities": {"controlnet": "supported"},
                            "controlPolicy": {"controls": []},
                        }
                    ]
                }

            def _node_available(inner_self, _name):
                return True

            def _lora_choice_by_leaf(inner_self, filename, node_name="LoraLoaderModelOnly"):
                if filename == "depth-control-lora.safetensors" and node_name == "Krea2ControlLoRALoader":
                    return "krea/depth-control-lora.safetensors"
                return None

        class TestMixin(server.DepthControlBridgeMixin, Parent):
            def _depth_preprocessor_ready(inner_self):
                return True

        result = TestMixin().model_support()
        controls = result["models"][0]["controlPolicy"]["controls"]
        depth = next(item for item in controls if item["id"] == "depth")
        self.assertEqual(depth["status"], "supported")
        self.assertEqual(depth["preprocessor"], "depth-anything-v2-small")
        self.assertEqual(depth["dependencyId"], "krea2-depth")

    def test_krea_depth_generation_routes_before_generic_control(self):
        class Parent:
            def _control_request(inner_self, request):
                return request.get("control")

            def _selected_product_model(inner_self, request):
                return {"id": "krea", "family": "krea2"}

            def generate(inner_self, request):
                return {"route": "parent"}

        class TestMixin(server.DepthControlBridgeMixin, Parent):
            def _generate_krea_depth(inner_self, request, model, control):
                return {"route": "krea-depth", "model": model["id"], "type": control["type"]}

        result = TestMixin().generate(
            {
                "mode": "txt2img",
                "control": {"enabled": True, "type": "depth", "image": {"name": "depth.png"}},
            }
        )
        self.assertEqual(result["route"], "krea-depth")

    def test_frontend_preprocesses_depth_source_and_exposes_preview(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-controlnet.js").read_text(encoding="utf-8")
        self.assertIn("/api/controlnet/preprocess/depth", source)
        self.assertIn("controlnet-depth-preview", source)
        self.assertIn("type === 'depth'", source)


if __name__ == "__main__":
    unittest.main()
