from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_krea_identity_edit as identity
import stableamd_v03_edit_server as server


def _base_krea_workflow():
    return {
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0], "seed": 123, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        }},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["11", 0], "text": "old prompt"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["11", 0], "text": ""}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea.safetensors"}},
        "11": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen.safetensors"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
    }


class _GraphParent:
    repo_root = Path(".")

    def _node_available(self, name):
        return True

    def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
        if filename == identity.KREA_IDENTITY_LORA_FILENAME:
            return f"krea/{filename}"
        return None


class _GraphBridge(identity.KreaIdentityEditBridgeMixin, _GraphParent):
    pass


class KreaIdentityDependencyTests(unittest.TestCase):
    def test_dependency_requires_both_nodes_and_identity_lora(self):
        class Parent:
            repo_root = Path(".")

            def _node_available(self, name):
                return name in {
                    "Krea2EditModelPatch",
                    "Krea2EditGroundedEncode",
                    "LoraLoaderModelOnly",
                }

            def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
                if filename == identity.KREA_IDENTITY_LORA_FILENAME:
                    return f"krea/{filename}"
                return None

        class Bridge(identity.KreaIdentityEditBridgeMixin, Parent):
            pass

        self.assertTrue(Bridge()._krea_identity_edit_ready())

        class MissingNodeParent(Parent):
            def _node_available(self, name):
                return name != "Krea2EditGroundedEncode"

        class MissingNodeBridge(identity.KreaIdentityEditBridgeMixin, MissingNodeParent):
            pass

        self.assertFalse(MissingNodeBridge()._krea_identity_edit_ready())

    def test_dependency_metadata_is_pinned_and_installable(self):
        dep = identity.KreaIdentityEditBridgeMixin._dependency_descriptor_static()
        self.assertEqual(dep["id"], "krea2-identity-edit-v1.2")
        self.assertTrue(dep["installable"])
        self.assertEqual(dep["plugin"]["repository"], "https://github.com/lbouaraba/comfyui-krea2edit.git")
        self.assertEqual(dep["plugin"]["commit"], identity.KREA_IDENTITY_PLUGIN_COMMIT)
        self.assertEqual(dep["model"]["repository"], "conradlocke/krea2-identity-edit")
        self.assertEqual(dep["model"]["filename"], "krea2_identity_edit_v1_2.safetensors")
        self.assertEqual(dep["model"]["sizeBytes"], 1_828_256_432)
        self.assertEqual(
            dep["model"]["sha256"],
            "6adf9a69cc9502d286db7b69964d37da7e9cfe4b05b4d004bc275f087d3fd3cf",
        )

    def test_api_exposes_dependency_and_validates_install_request(self):
        class Bridge:
            def krea_identity_dependency(self):
                return {"id": identity.KREA_IDENTITY_DEPENDENCY_ID, "ready": False}

            def install_krea_identity_dependency(self):
                return {"id": identity.KREA_IDENTITY_DEPENDENCY_ID, "installed": True}

        api = server.StableAmdApi(Bridge())
        status, payload = api.dispatch("GET", "/api/krea-identity/dependency")
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], identity.KREA_IDENTITY_DEPENDENCY_ID)

        status, payload = api.dispatch("POST", "/api/krea-identity/install", b"{}")
        self.assertEqual(status, 200)
        self.assertTrue(payload["installed"])

        status, payload = api.dispatch(
            "POST", "/api/krea-identity/install", b'{"id":"krea2-identity-edit-v1.2"}'
        )
        self.assertEqual(status, 200)

        status, payload = api.dispatch("POST", "/api/krea-identity/install", b'{"id":"wrong"}')
        self.assertEqual(status, 400)
        self.assertIn("krea2-identity-edit-v1.2", payload["error"])

        status, payload = api.dispatch("POST", "/api/krea-identity/install", b'{"unexpected":true}')
        self.assertEqual(status, 400)
        self.assertIn("Unsupported", payload["error"])


class KreaIdentityGraphTests(unittest.TestCase):
    def test_single_reference_graph_uses_training_matched_identity_path(self):
        graph = _GraphBridge()._inject_krea_identity_edit(_base_krea_workflow(), {
            "image_name": "source.png",
            "prompt": "same person character sheet",
            "width": 1792,
            "height": 1024,
        })
        sampler = graph["3"]["inputs"]
        self.assertEqual(graph["5"]["inputs"]["width"], 1792)
        self.assertEqual(graph["5"]["inputs"]["height"], 1024)
        self.assertEqual(sampler["steps"], 10)
        self.assertEqual(sampler["cfg"], 1.0)
        self.assertEqual(sampler["sampler_name"], "euler")
        self.assertEqual(sampler["scheduler"], "simple")
        self.assertEqual(sampler["denoise"], 1.0)

        lora = next(node for node in graph.values() if node.get("class_type") == "LoraLoaderModelOnly")
        self.assertEqual(lora["inputs"]["lora_name"], f"krea/{identity.KREA_IDENTITY_LORA_FILENAME}")
        self.assertEqual(lora["inputs"]["strength_model"], 1.0)

        patch = next(node for node in graph.values() if node.get("class_type") == "Krea2EditModelPatch")
        self.assertEqual(patch["inputs"]["fit_mode"], "fit")
        self.assertEqual(patch["inputs"]["ref_boost"], 4.0)
        self.assertEqual(patch["inputs"]["target_latent"], ["5", 0])
        self.assertIn("source_image", patch["inputs"])
        self.assertIn("vae", patch["inputs"])
        self.assertNotIn("source_latent_b", patch["inputs"])

        grounded = [node for node in graph.values() if node.get("class_type") == "Krea2EditGroundedEncode"]
        self.assertEqual(len(grounded), 1)
        self.assertEqual(grounded[0]["inputs"]["grounding_px"], 1024)
        self.assertEqual(sampler["positive"], [next(k for k, v in graph.items() if v is grounded[0]), 0])
        self.assertFalse(any(node.get("class_type") == "TextEncodeKrea2OstrisEdit" for node in graph.values()))

    def test_two_reference_detailer_uses_generated_crop_then_original_identity(self):
        graph = _GraphBridge()._inject_krea_identity_edit(_base_krea_workflow(), {
            "image_name": "generated-head.png",
            "identity_image_name": "original-face.png",
            "prompt": "correct identity only",
            "width": 768,
            "height": 896,
        })
        patch = next(node for node in graph.values() if node.get("class_type") == "Krea2EditModelPatch")
        self.assertIn("source_latent_b", patch["inputs"])
        self.assertIn("source_image_b", patch["inputs"])
        self.assertEqual(patch["inputs"]["ref_boost"], 4.0)
        self.assertEqual(patch["inputs"]["ref_boost_a"], 1.0)
        grounded = next(node for node in graph.values() if node.get("class_type") == "Krea2EditGroundedEncode")
        self.assertIn("image_b", grounded["inputs"])
        self.assertEqual(grounded["inputs"]["grounding_px"], 1024)
        self.assertEqual(graph["5"]["inputs"]["width"], 768)
        self.assertEqual(graph["5"]["inputs"]["height"], 896)

    def test_identity_graph_rejects_unaligned_or_oversized_targets(self):
        bridge = _GraphBridge()
        with self.assertRaisesRegex(identity.base.StableAmdBridgeError, "divisible by 16"):
            bridge._inject_krea_identity_edit(_base_krea_workflow(), {
                "image_name": "source.png", "prompt": "x", "width": 769, "height": 896,
            })
        with self.assertRaisesRegex(identity.base.StableAmdBridgeError, "2 MP"):
            bridge._inject_krea_identity_edit(_base_krea_workflow(), {
                "image_name": "source.png", "prompt": "x", "width": 2048, "height": 1024,
            })


if __name__ == "__main__":
    unittest.main()
