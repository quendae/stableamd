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
import stableamd_v03_character_sheet_face_guard as face_guard


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

        class Bridge(
            face_guard.CharacterSheetV2FacePanelGuardBridgeMixin,
            face_refine.CharacterSheetV2FaceRefineBridgeMixin,
            Parent,
        ):
            def _prepare_v2_tight_detail_context(self, *args, **kwargs):
                calls.append(("prepare-tight",))
                raise AssertionError("FACE close-up must not run the second tight-face pass")

        result = Bridge()._refine_v2_panel({}, {}, self._panel(), {})

        self.assertEqual(result["path"], Path("face-first-pass.png"))
        self.assertEqual(result["detailerStatus"], "completed")
        self.assertEqual(result["faceIdentityStatus"], "skipped")
        self.assertEqual(result["faceIdentitySkipped"], "close-up-panel")
        self.assertEqual(calls, [("first-pass", "face")])

    def test_front_still_flows_through_tight_refine_layer(self):
        calls: list[tuple] = []

        class Parent:
            def _refine_v2_panel(self, request, model, panel, source):
                calls.append(("parent-first-pass", panel.role))
                return {"role": panel.role, "path": Path("front-first-pass.png"), "detailerStatus": "completed"}

        class Bridge(
            face_guard.CharacterSheetV2FacePanelGuardBridgeMixin,
            face_refine.CharacterSheetV2FaceRefineBridgeMixin,
            Parent,
        ):
            def _prepare_v2_tight_detail_context(self, panel, first_path, source):
                calls.append(("prepare-tight", panel.role))
                return None

        panel = sheetv2.CharacterSheetV2Panel(
            role="front",
            index=1,
            path=Path("front.png"),
            box=(0, 0, 358, 1024),
            detail_box=(5, 15, 353, 1009),
        )
        result = Bridge()._refine_v2_panel({}, {}, panel, {})

        self.assertEqual(result["path"], Path("front-first-pass.png"))
        self.assertEqual(result["faceIdentityStatus"], "skipped")
        self.assertEqual(result["faceIdentitySkipped"], "no-face")
        self.assertEqual(calls, [("parent-first-pass", "front"), ("prepare-tight", "front")])


if __name__ == "__main__":
    unittest.main()
