import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from model_support import load_model_support_catalog, resolve_model_support, summarize_model_support


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
        self.assertEqual(sdxl["capabilities"]["img2img"], "supported")
        self.assertEqual(sdxl["capabilities"]["inpaint"], "supported")
        self.assertEqual(sdxl["capabilities"]["lora"], "supported")
        self.assertTrue(sdxl["loraPolicy"]["orderedStack"])
        self.assertEqual(sdxl["loraPolicy"]["maxStack"], 8)
        self.assertTrue(sdxl["loraPolicy"]["perEntryModelStrength"])
        self.assertTrue(sdxl["loraPolicy"]["perEntryClipStrength"])

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
        self.assertEqual(unknown["loraPolicy"]["maxStack"], 0)

        flux = resolve_model_support(catalog, {"id": "flux", "family": "flux", "name": "flux1-dev.safetensors"})
        self.assertEqual(flux["capabilities"]["txt2img"], "planned")
        self.assertEqual(flux["loraPolicy"]["maxStack"], 0)

    def test_support_summary_is_product_ready_without_running_generation(self):
        catalog = load_model_support_catalog(REPO_ROOT)
        summary = summarize_model_support(
            catalog,
            [
                {"id": "mdl_sdxl", "family": "sdxl", "name": "sd_xl_base_1.0.safetensors"},
                {"id": "mdl_flux", "family": "flux", "name": "flux1-dev.safetensors"},
            ],
        )

        self.assertEqual(summary["catalogVersion"], "0.3")
        self.assertIn("inpaint", summary["modes"])
        self.assertEqual(summary["models"][0]["provider"], "sdxl-checkpoint")
        self.assertEqual(summary["models"][0]["capabilities"]["txt2img"], "supported")
        self.assertEqual(summary["models"][0]["capabilities"]["img2img"], "supported")
        self.assertEqual(summary["models"][0]["capabilities"]["inpaint"], "supported")
        self.assertEqual(summary["models"][0]["loraPolicy"]["maxStack"], 8)
        self.assertEqual(summary["models"][1]["capabilities"]["txt2img"], "planned")


if __name__ == "__main__":
    unittest.main()
