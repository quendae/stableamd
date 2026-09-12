import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from model_support import load_model_support_catalog, resolve_model_support
from stableamd_server import StableAmdApi


class SupportBridge:
    def __init__(self):
        self.calls = []

    def model_support(self):
        self.calls.append(("model_support", None))
        return {
            "catalogVersion": "0.3",
            "modes": ["txt2img", "img2img", "inpaint", "controlnet", "lora"],
            "models": [
                {
                    "id": "mdl_sdxl",
                    "family": "sdxl",
                    "provider": "sdxl-checkpoint",
                    "capabilities": {"txt2img": "supported", "img2img": "planned"},
                }
            ],
        }


class StableAmdV03SupportTests(unittest.TestCase):
    def test_catalog_declares_explicit_capabilities_and_asset_layouts(self):
        catalog = load_model_support_catalog(REPO_ROOT)
        self.assertEqual(catalog["schemaVersion"], 1)
        self.assertIn("sdxl", catalog["families"])
        self.assertIn("flux", catalog["families"])
        self.assertIn("krea2", catalog["families"])

        sdxl = catalog["families"]["sdxl"]
        self.assertEqual(sdxl["provider"], "sdxl-checkpoint")
        self.assertEqual(sdxl["assetMode"], "checkpoint")
        self.assertEqual(sdxl["capabilities"]["txt2img"], "supported")
        self.assertEqual(sdxl["capabilities"]["lora"], "supported")
        self.assertEqual(sdxl["capabilities"]["inpaint"], "planned")

        flux = catalog["families"]["flux"]
        self.assertEqual(flux["assetMode"], "bundle")
        self.assertIn("diffusion_model", flux["requiredAssetRoles"])
        self.assertIn("text_encoder", flux["requiredAssetRoles"])
        self.assertIn("vae", flux["requiredAssetRoles"])
        self.assertEqual(flux["capabilities"]["txt2img"], "planned")

        krea = catalog["families"]["krea2"]
        self.assertEqual(krea["capabilities"]["txt2img"], "planned")

    def test_support_resolution_never_upgrades_unknown_or_planned_models_to_supported(self):
        catalog = load_model_support_catalog(REPO_ROOT)

        unknown = resolve_model_support(catalog, {"id": "mystery", "family": "unknown", "name": "mystery.safetensors"})
        self.assertEqual(unknown["provider"], "unsupported")
        self.assertTrue(all(value == "unsupported" for value in unknown["capabilities"].values()))

        flux = resolve_model_support(catalog, {"id": "flux", "family": "flux", "name": "flux1-dev.safetensors"})
        self.assertEqual(flux["capabilities"]["txt2img"], "planned")

    def test_product_api_exposes_model_support_without_running_generation(self):
        bridge = SupportBridge()
        api = StableAmdApi(bridge)

        status, payload = api.dispatch("GET", "/api/model-support")
        self.assertEqual(status, 200)
        self.assertEqual(payload["models"][0]["provider"], "sdxl-checkpoint")
        self.assertEqual(bridge.calls, [("model_support", None)])


if __name__ == "__main__":
    unittest.main()
