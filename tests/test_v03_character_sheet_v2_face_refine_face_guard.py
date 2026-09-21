from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet_v2 as sheetv2
import stableamd_v03_character_sheet_face_refine as face_refine


class CharacterSheetV2FacePanelGuardTests(unittest.TestCase):
    @staticmethod
    def _panel() -> sheetv2.CharacterSheetV2Panel:
        return sheetv2.CharacterSheetV2Panel(
            role="face",
            index=0,
            path=Path("face.png"),
            box=(0, 0, 358, 1024),
            detail_box=(5, 15, 353, 1009),
        )

    def test_face_closeup_keeps_first_pass_and_never_runs_tight_face_pass(self):
        calls: list[tuple] = []

        class Parent:
            def _refine_v2_panel(self, request, model, panel, source):
                calls.append(("first-pass", panel.role))
                return {
                    "role": panel.role,
                    "path": Path("face-first-pass.png"),
                    "detailerStatus": "completed",
                    "detailerGenerationSeconds": 2.0,
                }

        class Bridge(face_refine.CharacterSheetV2FaceRefineBridgeMixin, Parent):
            def _prepare_v2_tight_detail_context(self, *args, **kwargs):
                calls.append(("prepare-tight",))
                raise AssertionError("FACE close-up must not run the second tight-face pass")

        bridge = Bridge()
        self.assertFalse(bridge._should_tight_face_refine("face"))
        result = bridge._refine_v2_panel({}, {}, self._panel(), {})

        self.assertEqual(result["path"], Path("face-first-pass.png"))
        self.assertEqual(result["detailerStatus"], "completed")
        self.assertEqual(result["faceIdentityStatus"], "skipped")
        self.assertEqual(result["faceIdentitySkipped"], "close-up-panel")
        self.assertEqual(calls, [("first-pass", "face")])


if __name__ == "__main__":
    unittest.main()
