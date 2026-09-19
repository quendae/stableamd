import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_lora_server as lora_server
import stableamd_v03_server as v03


class StableAmdV03OutpaintMetadataTests(unittest.TestCase):
    def test_edit_context_accepts_feather_overlap_and_rejects_invalid_values(self):
        valid = {
            "kind": "outpaint",
            "sourcePromptId": "source-1",
            "sourceImagePath": "C:/StableAMD/source.png",
            "blendOverlap": 64,
            "margins": {"left": 256, "right": 128, "top": 0, "bottom": 64},
        }
        lora_server.StableAmdApi._validate_edit_context(valid)

        for invalid in (-8, 10, 264, True, "64"):
            payload = dict(valid)
            payload["blendOverlap"] = invalid
            with self.assertRaises(ValueError, msg=invalid):
                lora_server.StableAmdApi._validate_edit_context(payload)

    def test_outpaint_result_persists_source_relationship_margins_and_blend_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            history_root = repo_root / ".runtime" / "stableamd" / "history"
            history_root.mkdir(parents=True)
            history_path = history_root / "outpaint.json"
            history_path.write_text(json.dumps({"mode": "inpaint", "promptId": "result-1"}), encoding="utf-8")

            bridge = lora_server.PowerShellBridge(repo_root, powershell=sys.executable)
            request = {
                "prompt": "continue the same room naturally",
                "mode": "inpaint",
                "editContext": {
                    "kind": "outpaint",
                    "sourcePromptId": "source-1",
                    "sourceImagePath": "C:/StableAMD/source.png",
                    "blendOverlap": 64,
                    "margins": {"left": 256, "right": 128, "top": 0, "bottom": 64},
                },
            }
            delegated = {"HistoryPath": str(history_path), "Mode": "inpaint"}
            with patch.object(v03.PowerShellBridge, "_generate_inpaint", return_value=delegated):
                result = bridge._generate_inpaint(request)

            stored = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["mode"], "outpaint")
            self.assertEqual(stored["editOperation"], "outpaint")
            self.assertEqual(stored["sourcePromptId"], "source-1")
            self.assertEqual(stored["outpaintMargins"]["left"], 256)
            self.assertEqual(stored["outpaintBlendOverlap"], 64)
            self.assertEqual(result["Mode"], "outpaint")
            self.assertEqual(result["OutpaintBlendOverlap"], 64)


if __name__ == "__main__":
    unittest.main()
