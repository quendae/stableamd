from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_EDIT_PATH = BACKEND / "stableamd_v03_krea_edit.py"
FINAL_SERVER_PATH = BACKEND / "stableamd_v03_edit_server.py"
FRONTEND_PATH = FRONTEND / "app-krea-edit.js"
INDEX_PATH = FRONTEND / "index.html"
SUPPORT_PATH = ROOT / "config" / "model-support.v0.3.json"


class StableAmdKreaImageEditTests(unittest.TestCase):
    def _load_edit_module(self):
        if not KREA_EDIT_PATH.is_file():
            self.fail("Krea image-edit bridge module has not been implemented yet.")
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        spec = importlib.util.spec_from_file_location("stableamd_v03_krea_edit_test", KREA_EDIT_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_final_bridge_composes_krea_image_edit_before_pose_control(self):
        source = FINAL_SERVER_PATH.read_text(encoding="utf-8")
        self.assertIn("import stableamd_v03_krea_edit as kreaedit", source)
        self.assertIn("from stableamd_v03_krea_edit import KreaImageEditBridgeMixin", source)
        self.assertIn("KreaImageEditBridgeMixin,\n    PoseControlBridgeMixin,", source)

    def test_krea_img2img_catalog_stays_runtime_gated(self):
        payload = json.loads(SUPPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["families"]["krea2"]["capabilities"]["img2img"], "planned")

    def test_krea_edit_support_turns_on_only_when_required_nodes_are_ready(self):
        module = self._load_edit_module()

        class Parent:
            ready = True

            def model_support(self):
                return {
                    "models": [
                        {
                            "id": "krea",
                            "family": "krea2",
                            "capabilities": {"txt2img": "supported", "img2img": "planned"},
                        }
                    ]
                }

            def _node_available(self, _name):
                return self.ready

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        bridge = Bridge()
        supported = bridge.model_support()["models"][0]
        self.assertEqual(supported["capabilities"]["img2img"], "supported")
        self.assertEqual(supported["editPolicy"]["label"], "Image Edit")
        self.assertTrue(supported["editPolicy"]["wholeImage"])
        self.assertEqual(supported["editPolicy"]["referenceScaler"], "FluxKontextImageScale")

        bridge.ready = False
        gated = bridge.model_support()["models"][0]
        self.assertEqual(gated["capabilities"]["img2img"], "planned")

    def test_krea_edit_graph_uses_official_reference_conditioning_and_source_size(self):
        module = self._load_edit_module()

        class Parent:
            def _node_available(self, _name):
                return True

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        workflow = {
            "10": {"class_type": "UNETLoader", "inputs": {}},
            "11": {"class_type": "CLIPLoader", "inputs": {"device": "cpu"}},
            "12": {"class_type": "VAELoader", "inputs": {}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["41", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                    "cfg": 1.0,
                },
            },
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "change the jacket to red"}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        }
        result = Bridge()._inject_krea_image_edit(workflow, {"image_name": "source.png"})

        self.assertEqual(result["80"]["class_type"], "LoadImage")
        self.assertEqual(result["81"]["class_type"], "FluxKontextImageScale")
        self.assertEqual(result["82"]["class_type"], "GetImageSize")
        self.assertEqual(result["83"]["class_type"], "Krea2OstrisEditModelPatch")
        self.assertEqual(result["83"]["inputs"]["model"], ["41", 0])
        self.assertTrue(result["83"]["inputs"]["kv_cache"])
        self.assertEqual(result["84"]["class_type"], "SelectVAEDevice")
        self.assertEqual(result["84"]["inputs"]["device"], "gpu:0")
        self.assertEqual(result["85"]["class_type"], "TextEncodeKrea2OstrisEdit")
        self.assertEqual(result["85"]["inputs"]["image1"], ["81", 0])
        self.assertEqual(result["85"]["inputs"]["prompt"], "change the jacket to red")
        self.assertEqual(result["87"]["inputs"]["reference_latents_method"], "index_timestep_zero")
        self.assertEqual(result["88"]["inputs"]["reference_latents_method"], "index_timestep_zero")
        self.assertEqual(result["5"]["inputs"]["width"], ["82", 0])
        self.assertEqual(result["5"]["inputs"]["height"], ["82", 1])
        self.assertEqual(result["3"]["inputs"]["model"], ["83", 0])
        self.assertEqual(result["3"]["inputs"]["positive"], ["87", 0])
        self.assertEqual(result["3"]["inputs"]["negative"], ["88", 0])
        self.assertNotIn("image1", result["86"]["inputs"])
        self.assertNotIn("vae", result["86"]["inputs"])
        self.assertEqual(result["8"]["inputs"]["vae"], ["84", 0])
        self.assertEqual(result["11"]["inputs"]["device"], "default")

    def test_krea_image_edit_route_stages_source_and_reuses_async_krea_provider(self):
        module = self._load_edit_module()
        source = KREA_EDIT_PATH.read_text(encoding="utf-8")
        self.assertIn('mode == "img2img"', source)
        self.assertIn("base.stage_input_image", source)
        self.assertIn('clean["mode"] = "txt2img"', source)
        self.assertIn('clean.pop("inputImage", None)', source)
        self.assertIn('clean.pop("denoise", None)', source)
        self.assertIn("super()._generate_krea2_turbo(clean, selected)", source)
        self.assertIn('result["Mode"] = "img2img"', source)
        self.assertIn('result["EditOperation"] = "image-edit"', source)
        self.assertTrue(hasattr(module.KreaImageEditBridgeMixin, "generate"))

    def test_frontend_adapter_loads_before_v02_and_presents_whole_image_edit_without_denoise(self):
        self.assertTrue(FRONTEND_PATH.is_file(), "Krea Image Edit frontend adapter is missing.")
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        index = INDEX_PATH.read_text(encoding="utf-8")
        self.assertIn('"Image Edit"', source)
        self.assertIn('family === "krea2"', source)
        self.assertIn("whole-image", source.lower())
        self.assertIn("Edit instruction", source)
        self.assertIn("delete payload.denoise", source)
        self.assertIn('/app-krea-edit.js', index)
        self.assertLess(index.index('/app-krea-edit.js'), index.index('/app-v02.js'))


if __name__ == "__main__":
    unittest.main()
