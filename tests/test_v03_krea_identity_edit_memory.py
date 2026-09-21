from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_krea_identity_edit as identity
import stableamd_v03_krea_identity_graph as graphfix


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


class _GraphBridge(
    graphfix.KreaIdentityGraphBridgeMixin,
    identity.KreaIdentityEditBridgeMixin,
    _GraphParent,
):
    pass


class KreaIdentityMemoryTests(unittest.TestCase):
    def test_raw_references_are_scaled_only_for_required_source_latents(self):
        graph = _GraphBridge()._inject_krea_identity_edit(_base_krea_workflow(), {
            "image_name": "full-resolution-source.png",
            "identity_image_name": "full-resolution-identity.png",
            "prompt": "preserve identity",
            "width": 1792,
            "height": 1024,
        })

        image_nodes = {
            node_id: node
            for node_id, node in graph.items()
            if isinstance(node, dict) and node.get("class_type") == "LoadImage"
        }
        source_image_id = next(
            node_id for node_id, node in image_nodes.items()
            if node["inputs"]["image"] == "full-resolution-source.png"
        )
        identity_image_id = next(
            node_id for node_id, node in image_nodes.items()
            if node["inputs"]["image"] == "full-resolution-identity.png"
        )

        scale_nodes = {
            node_id: node
            for node_id, node in graph.items()
            if isinstance(node, dict) and node.get("class_type") == "ImageScale"
        }
        source_scale_id = next(
            node_id for node_id, node in scale_nodes.items()
            if node["inputs"].get("image") == [source_image_id, 0]
        )
        identity_scale_id = next(
            node_id for node_id, node in scale_nodes.items()
            if node["inputs"].get("image") == [identity_image_id, 0]
        )

        for scale_id in (source_scale_id, identity_scale_id):
            self.assertEqual(graph[scale_id]["inputs"]["upscale_method"], "lanczos")
            self.assertEqual(graph[scale_id]["inputs"]["width"], 1792)
            self.assertEqual(graph[scale_id]["inputs"]["height"], 1024)
            self.assertEqual(graph[scale_id]["inputs"]["crop"], "center")

        vae_encodes = [
            node for node in graph.values()
            if isinstance(node, dict) and node.get("class_type") == "VAEEncode"
        ]
        self.assertEqual(len(vae_encodes), 2)
        encoded_pixel_refs = {tuple(node["inputs"]["pixels"]) for node in vae_encodes}
        self.assertEqual(encoded_pixel_refs, {(source_scale_id, 0), (identity_scale_id, 0)})

        patch = next(node for node in graph.values() if node.get("class_type") == "Krea2EditModelPatch")["inputs"]
        self.assertEqual(patch["source_image"], [source_image_id, 0])
        self.assertEqual(patch["source_image_b"], [identity_image_id, 0])
        grounded = next(node for node in graph.values() if node.get("class_type") == "Krea2EditGroundedEncode")["inputs"]
        self.assertEqual(grounded["image"], [source_image_id, 0])
        self.assertEqual(grounded["image_b"], [identity_image_id, 0])


if __name__ == "__main__":
    unittest.main()
