from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as edit_server


ZIMAGE = {
    "id": "bnd_zimage",
    "name": "Z-Image Turbo",
    "family": "z-image-turbo",
    "provider": "z-image-turbo-bundle",
    "assetMode": "bundle",
}


class FakeBridge(edit_server.PowerShellBridge):
    def __init__(self, patch_ready: bool = False, legacy_patch: bool = False):
        super().__init__(REPO_ROOT, powershell=sys.executable)
        self.patch_ready = patch_ready
        self.legacy_patch = legacy_patch

    def models(self):
        return [dict(ZIMAGE)]

    def _comfy_json(self, relative_path):
        if relative_path == "object_info/ModelPatchLoader":
            options = []
            if self.patch_ready:
                options.append(edit_server.ZIMAGE_FUN_PATCH)
            if self.legacy_patch:
                options.append(edit_server.ZIMAGE_FUN_LEGACY_PATCH)
            return {
                "ModelPatchLoader": {
                    "input": {
                        "required": {
                            "name": ["COMBO", {"options": options}],
                        }
                    }
                }
            }
        raise AssertionError(relative_path)


class StableAmdV03ZImageEditTests(unittest.TestCase):
    def test_patch_discovery_enables_inpaint_capability_only_for_inpaint_capable_union_21(self):
        ready = FakeBridge(patch_ready=True).model_support()
        ready_model = ready["models"][0]
        self.assertEqual(ready_model["family"], "z-image-turbo")
        self.assertEqual(ready_model["capabilities"]["inpaint"], "supported")
        self.assertEqual(ready_model["capabilities"]["img2img"], "planned")
        self.assertEqual(ready_model["capabilities"]["controlnet"], "planned")

        missing = FakeBridge().model_support()
        self.assertEqual(missing["models"][0]["capabilities"]["inpaint"], "planned")

        legacy = FakeBridge(legacy_patch=True).model_support()
        self.assertEqual(legacy["models"][0]["capabilities"]["inpaint"], "planned")
        with self.assertRaisesRegex(edit_server.base.StableAmdBridgeError, "older control-only patch"):
            FakeBridge(legacy_patch=True)._zimage_fun_patch_name(required=True)

    def test_native_edit_patch_is_pinned_to_16gib_friendly_distilled_union_21(self):
        self.assertEqual(
            edit_server.ZIMAGE_FUN_PATCH,
            "Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors",
        )
        self.assertEqual(edit_server.ZIMAGE_FUN_PATCH_BYTES, 2016627488)
        self.assertEqual(
            edit_server.ZIMAGE_FUN_PATCH_SHA256,
            "3ea098db9bd145be525c7e2366920b6d76c5ffd46b3d7aa8169bbc943fdaee35",
        )

    def test_native_edit_graph_uses_pinned_fun_control_inpaint_nodes(self):
        workflow = FakeBridge(patch_ready=True)._zimage_edit_workflow(
            diffusion_name="z_image_turbo_bf16.safetensors",
            encoder_name="qwen_3_4b.safetensors",
            vae_name="ae.safetensors",
            model_patch_name=edit_server.ZIMAGE_FUN_PATCH,
            input_image_name="StableAMD_test.png",
            prompt="replace the sky",
            width=1024,
            height=1024,
            seed=7,
            steps=8,
            cfg=1.0,
            sampler="res_multistep",
            scheduler="simple",
            filename_prefix="StableAMD_TEST",
        )

        self.assertEqual(workflow["45"]["class_type"], "ModelPatchLoader")
        self.assertEqual(workflow["45"]["inputs"]["name"], edit_server.ZIMAGE_FUN_PATCH)
        self.assertEqual(workflow["46"]["class_type"], "ZImageFunControlnet")
        self.assertEqual(workflow["46"]["inputs"]["model"], ["28", 0])
        self.assertEqual(workflow["46"]["inputs"]["model_patch"], ["45", 0])
        self.assertEqual(workflow["46"]["inputs"]["inpaint_image"], ["41", 0])
        self.assertEqual(workflow["46"]["inputs"]["mask"], ["44", 0])
        self.assertEqual(workflow["11"]["inputs"]["model"], ["46", 0])
        self.assertEqual(workflow["3"]["inputs"]["model"], ["11", 0])
        self.assertEqual(workflow["3"]["inputs"]["denoise"], 1.0)
        self.assertEqual(workflow["3"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(workflow["3"]["inputs"]["scheduler"], "simple")

    def test_launcher_and_backend_expose_edit_layer_and_model_patch_root(self):
        launcher = (REPO_ROOT / "scripts" / "Launch-StableAMD.ps1").read_text(encoding="utf-8-sig")
        backend = (REPO_ROOT / "scripts" / "Start-StableAMD.ps1").read_text(encoding="utf-8-sig")
        defaults = (REPO_ROOT / "config" / "stableamd.default.json").read_text(encoding="utf-8-sig")

        self.assertIn("stableamd_v03_edit_server.py", launcher)
        self.assertIn("model_patches", backend)
        self.assertIn("modelPatches", defaults)


if __name__ == "__main__":
    unittest.main()
