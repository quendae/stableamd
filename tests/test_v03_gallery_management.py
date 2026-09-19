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
import upscale_support


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

    def test_upscale_scale_is_inferred_for_gallery_metadata(self):
        self.assertEqual(upscale_support.infer_upscale_scale("RealESRGAN_x2plus.pth"), 2)
        self.assertEqual(upscale_support.infer_upscale_scale("4x-UltraSharp.pth"), 4)
        self.assertEqual(upscale_support.infer_upscale_scale("8x_NMKD.pth"), 8)
        self.assertIsNone(upscale_support.infer_upscale_scale("generic-upscaler.pth"))


if __name__ == "__main__":
    unittest.main()
