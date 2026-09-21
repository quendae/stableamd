import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_server as base
import stableamd_v03_vector as vector
import upscale_support


class _VectorDeleteParent:
    def __init__(self, repo_root):
        self.repo_root = Path(repo_root).resolve()
        self.delegated: list[str] = []

    def delete_history(self, prompt_id):
        self.delegated.append(str(prompt_id))
        return {"deleted": False, "promptId": str(prompt_id), "delegated": True}


class _VectorDeleteProbe(vector.VectorBridgeMixin, _VectorDeleteParent):
    pass


class StableAmdV03GalleryManagementTests(unittest.TestCase):
    def test_history_delete_removes_record_and_managed_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            history_root = repo_root / ".runtime" / "stableamd" / "history"
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            history_root.mkdir(parents=True)
            output_root.mkdir(parents=True)
            image = output_root / "delete-me.png"
            image.write_bytes(b"png")
            record_path = history_root / "20260913_test.json"
            record_path.write_text(
                json.dumps({"promptId": "prompt-delete", "imagePath": str(image)}),
                encoding="utf-8",
            )

            bridge = base.PowerShellBridge(repo_root, powershell=sys.executable)
            result = bridge.delete_history("prompt-delete")

            self.assertTrue(result["deleted"])
            self.assertFalse(record_path.exists())
            self.assertFalse(image.exists())

    def test_history_delete_refuses_unknown_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = base.PowerShellBridge(Path(temporary), powershell=sys.executable)
            result = bridge.delete_history("does-not-exist")
            self.assertFalse(result["deleted"])

    def test_vector_delete_removes_final_assets_owned_intermediates_and_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary).resolve()
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            vector_root = output_root / "vector"
            history_root = repo_root / ".runtime" / "stableamd" / "history"
            vector_root.mkdir(parents=True)
            history_root.mkdir(parents=True)

            svg = vector_root / "vector-1.svg"
            preview = vector_root / "vector-1-preview.png"
            child = output_root / "child-raster.png"
            prepared = vector_root / "owned-working.png"
            for path in (svg, preview, child, prepared):
                path.write_bytes(b"asset")

            record_path = history_root / "vector-1.json"
            record_path.write_text(
                json.dumps({
                    "promptId": "vector-1",
                    "assetType": "svg",
                    "sanitized": True,
                    "svgPath": str(svg),
                    "previewPath": str(preview),
                    "ownedIntermediatePaths": [str(child), str(prepared)],
                }),
                encoding="utf-8",
            )

            bridge = _VectorDeleteProbe(repo_root)
            result = bridge.delete_history("vector-1")

            self.assertTrue(result["deleted"])
            self.assertFalse(record_path.exists())
            for path in (svg, preview, child, prepared):
                self.assertFalse(path.exists(), path)
            self.assertEqual(bridge.delegated, [])

    def test_vector_delete_never_deletes_owned_path_outside_managed_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary).resolve()
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            vector_root = output_root / "vector"
            history_root = repo_root / ".runtime" / "stableamd" / "history"
            vector_root.mkdir(parents=True)
            history_root.mkdir(parents=True)

            svg = vector_root / "vector-safe.svg"
            preview = vector_root / "vector-safe-preview.png"
            safe_child = output_root / "safe-child.png"
            external = repo_root / "must-survive.txt"
            for path in (svg, preview, safe_child, external):
                path.write_bytes(b"asset")

            record_path = history_root / "vector-safe.json"
            record_path.write_text(
                json.dumps({
                    "promptId": "vector-safe",
                    "assetType": "svg",
                    "sanitized": True,
                    "svgPath": str(svg),
                    "previewPath": str(preview),
                    "ownedIntermediatePaths": [str(safe_child), str(external)],
                }),
                encoding="utf-8",
            )

            result = _VectorDeleteProbe(repo_root).delete_history("vector-safe")

            self.assertTrue(result["deleted"])
            self.assertFalse(svg.exists())
            self.assertFalse(preview.exists())
            self.assertFalse(safe_child.exists())
            self.assertTrue(external.exists())
            self.assertIn(str(external), result["refusedOwnedPaths"])
            self.assertFalse(record_path.exists())

    def test_non_vector_delete_delegates_to_existing_gallery_lifecycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = _VectorDeleteProbe(Path(temporary))
            result = bridge.delete_history("ordinary-raster")
            self.assertTrue(result["delegated"])
            self.assertEqual(bridge.delegated, ["ordinary-raster"])

    def test_upscale_scale_is_inferred_for_gallery_metadata(self):
        self.assertEqual(upscale_support.infer_upscale_scale("RealESRGAN_x2plus.pth"), 2)
        self.assertEqual(upscale_support.infer_upscale_scale("4x-UltraSharp.pth"), 4)
        self.assertEqual(upscale_support.infer_upscale_scale("8x_NMKD.pth"), 8)
        self.assertIsNone(upscale_support.infer_upscale_scale("generic-upscaler.pth"))


if __name__ == "__main__":
    unittest.main()
