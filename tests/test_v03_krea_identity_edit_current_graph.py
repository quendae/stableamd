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
import stableamd_v03_edit_server as server


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


def _current_krea_workflow():
    """Mirror scripts/StableAmd.Krea2.psm1 rather than the old test-only graph."""
    return {
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea.safetensors"}},
        "11": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen.safetensors"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["11", 0], "text": "old prompt"}},
        "13": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "positive": ["6", 0], "negative": ["13", 0],
            "latent_image": ["5", 0], "seed": 123, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        }},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "StableAMD"}},
    }


def _renumbered_krea_workflow():
    return {
        "100": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea.safetensors"}},
        "110": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen.safetensors"}},
        "120": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "60": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["110", 0], "text": "old prompt"}},
        "130": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["60", 0]}},
        "50": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "30": {"class_type": "KSampler", "inputs": {
            "model": ["100", 0], "positive": ["60", 0], "negative": ["130", 0],
            "latent_image": ["50", 0], "seed": 123, "steps": 8, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        }},
        "80": {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0], "vae": ["120", 0]}},
        "90": {"class_type": "SaveImage", "inputs": {"images": ["80", 0], "filename_prefix": "StableAMD"}},
    }


class KreaIdentityCurrentGraphTests(unittest.TestCase):
    def test_final_server_composes_semantic_resolver_before_legacy_identity_mixin(self):
        mro = server.PowerShellBridge.__mro__
        self.assertLess(
            mro.index(graphfix.KreaIdentityGraphBridgeMixin),
            mro.index(identity.KreaIdentityEditBridgeMixin),
        )

    def test_current_krea_graph_with_conditioning_zero_out_is_supported(self):
        graph = _GraphBridge()._inject_krea_identity_edit(_current_krea_workflow(), {
            "image_name": "source.png",
            "prompt": "same person character sheet",
            "width": 1792,
            "height": 1024,
        })
        sampler = graph["3"]["inputs"]
        self.assertEqual(sampler["negative"], ["13", 0])
        patch = next(node for node in graph.values() if node.get("class_type") == "Krea2EditModelPatch")
        self.assertEqual(patch["inputs"]["target_latent"], ["5", 0])
        self.assertEqual(patch["inputs"]["vae"], ["12", 0])

    def test_identity_injection_resolves_semantic_anchors_not_node_numbers(self):
        graph = _GraphBridge()._inject_krea_identity_edit(_renumbered_krea_workflow(), {
            "image_name": "source.png",
            "prompt": "same person character sheet",
            "width": 1792,
            "height": 1024,
        })
        sampler = graph["30"]["inputs"]
        self.assertEqual(sampler["negative"], ["130", 0])
        self.assertEqual(graph["50"]["inputs"]["width"], 1792)
        self.assertEqual(graph["50"]["inputs"]["height"], 1024)
        patch = next(node for node in graph.values() if node.get("class_type") == "Krea2EditModelPatch")
        grounded = next(node for node in graph.values() if node.get("class_type") == "Krea2EditGroundedEncode")
        self.assertEqual(patch["inputs"]["target_latent"], ["50", 0])
        self.assertEqual(patch["inputs"]["vae"], ["120", 0])
        self.assertEqual(grounded["inputs"]["clip"], ["110", 0])


if __name__ == "__main__":
    unittest.main()
