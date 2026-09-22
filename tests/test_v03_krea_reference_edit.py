from __future__ import annotations

import base64
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
FRONTEND = ROOT / "app" / "frontend"
KREA_EDIT_PATH = BACKEND / "stableamd_v03_krea_edit.py"
FINAL_SERVER_PATH = BACKEND / "stableamd_v03_edit_server.py"
FRONTEND_PATH = FRONTEND / "app-krea-edit.js"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_edit_server as server


def tiny_png(name: str = "image.png") -> dict[str, str]:
    return {
        "name": name,
        "mimeType": "image/png",
        "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii"),
    }


class StableAmdKreaReferenceEditTests(unittest.TestCase):
    def _load_edit_module(self):
        spec = importlib.util.spec_from_file_location("stableamd_v03_krea_reference_test", KREA_EDIT_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_final_api_accepts_up_to_two_valid_references_for_img2img(self):
        api = server.StableAmdApi(object())
        request = {
            "prompt": "change the sofa",
            "mode": "img2img",
            "inputImage": tiny_png("source.png"),
            "references": [
                {"role": "style", "image": tiny_png("style.png")},
                {"role": "material", "image": tiny_png("material.png")},
            ],
        }
        validated = api._validate_generation(request)
        self.assertEqual([item["role"] for item in validated["references"]], ["style", "material"])

        with self.assertRaisesRegex(ValueError, "at most 2"):
            api._validate_generation({
                **request,
                "references": [
                    {"role": "style", "image": tiny_png("a.png")},
                    {"role": "material", "image": tiny_png("b.png")},
                    {"role": "content", "image": tiny_png("c.png")},
                ],
            })
        with self.assertRaisesRegex(ValueError, "style, material, or content"):
            api._validate_generation({
                **request,
                "references": [{"role": "other", "image": tiny_png("bad.png")}],
            })

    def test_final_server_expands_request_budget_for_source_plus_two_references(self):
        self.assertGreaterEqual(server.base.MAX_REQUEST_BYTES, 96 * 1024 * 1024)

    def test_krea_edit_policy_advertises_two_reference_roles(self):
        module = self._load_edit_module()

        class Parent:
            def model_support(self):
                return {
                    "models": [{
                        "id": "krea",
                        "family": "krea2",
                        "capabilities": {"txt2img": "supported", "img2img": "planned"},
                    }]
                }

            def _node_available(self, _name):
                return True

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        policy = Bridge().model_support()["models"][0]["editPolicy"]
        self.assertEqual(policy["referenceImages"]["max"], 2)
        self.assertEqual(policy["referenceImages"]["roles"], ["style", "material", "content"])

    def test_krea_edit_graph_attaches_two_references_as_image2_and_image3(self):
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
            "3": {"class_type": "KSampler", "inputs": {"model": ["10", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0], "cfg": 2.0}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "make the room warmer"}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        }
        result = Bridge()._inject_krea_image_edit(
            workflow,
            {
                "image_name": "source.png",
                "references": [
                    {"name": "style.png", "role": "style"},
                    {"name": "material.png", "role": "material"},
                ],
            },
        )
        self.assertEqual(result["89"]["class_type"], "LoadImage")
        self.assertEqual(result["89"]["inputs"]["image"], "style.png")
        self.assertEqual(result["90"]["class_type"], "LoadImage")
        self.assertEqual(result["90"]["inputs"]["image"], "material.png")
        self.assertEqual(result["85"]["inputs"]["image2"], ["89", 0])
        self.assertEqual(result["85"]["inputs"]["image3"], ["90", 0])
        self.assertEqual(result["86"]["inputs"]["image2"], ["89", 0])
        self.assertEqual(result["86"]["inputs"]["image3"], ["90", 0])

    def test_reference_roles_build_picture_2_and_picture_3_instruction(self):
        module = self._load_edit_module()
        compose = module.KreaImageEditBridgeMixin._compose_reference_prompt
        prompt = compose("replace the sofa covering", ["style", "material"])
        self.assertIn("Picture 1", prompt)
        self.assertIn("Picture 2", prompt)
        self.assertIn("style reference", prompt)
        self.assertIn("Picture 3", prompt)
        self.assertIn("material or texture reference", prompt)
        self.assertTrue(prompt.endswith("replace the sofa covering"))

    def test_result_metadata_records_both_reference_names_and_roles(self):
        module = self._load_edit_module()

        class Parent:
            pass

        class Bridge(module.KreaImageEditBridgeMixin, Parent):
            pass

        bridge = object.__new__(Bridge)
        result = {}
        bridge._persist_krea_image_edit_metadata(
            result,
            "source.png",
            references=[
                {"name": "style.png", "role": "style"},
                {"name": "material.png", "role": "material"},
            ],
        )
        self.assertEqual(
            result["ReferenceImages"],
            [
                {"name": "style.png", "role": "style"},
                {"name": "material.png", "role": "material"},
            ],
        )

    def test_frontend_exposes_second_reference_role_and_upload_contract(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn('id="krea-reference-enabled"', source)
        self.assertIn('id="krea-reference-role"', source)
        self.assertIn('id="krea-reference-image"', source)
        self.assertIn('id="krea-reference-2-enabled"', source)
        self.assertIn('id="krea-reference-role-2"', source)
        self.assertIn('id="krea-reference-image-2"', source)
        self.assertIn('Reference 1', source)
        self.assertIn('Reference 2', source)
        self.assertIn('value="style"', source)
        self.assertIn('value="material"', source)
        self.assertIn('value="content"', source)
        self.assertIn("readReferenceImage", source)
        self.assertIn("payload.references", source)
        self.assertIn("references.push", source)


if __name__ == "__main__":
    unittest.main()
