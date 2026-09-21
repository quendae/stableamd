from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import stableamd_v03_character_sheet_v2 as sheetv2


BASE_REQUEST = {
    "prompt": "keep the same identity",
    "mode": "img2img",
    "modelId": "krea",
    "inputImage": {"name": "character.png", "mimeType": "image/png", "dataBase64": "iVBORw0KGgo="},
    "editTask": "character-sheet",
    "characterSheetVersion": "v2",
    "characterSheetDetailer": True,
    "seed": 123,
}


def _panels():
    roles = ("face", "front", "three-quarter", "side", "back")
    return [
        sheetv2.CharacterSheetV2Panel(
            role=role,
            index=index,
            path=Path(f"{role}.png"),
            box=(index * 100, 0, (index + 1) * 100, 200),
            detail_box=(2, 3, 98, 197),
        )
        for index, role in enumerate(roles)
    ]


class CharacterSheetV2OrchestrationTests(unittest.TestCase):
    def _bridge(self, calls, *, fail_persist=False):
        class Staged:
            name = "source-v2.png"
            def unlink(self, missing_ok=False):
                calls.append(("unlink-source", missing_ok))

        class Parent:
            repo_root = Path(".")

            def _selected_product_model(self, request):
                return {"id": "krea", "family": "krea2", "assetMode": "bundle", "name": "Krea 2 Turbo"}

            def _krea_identity_edit_ready(self):
                return True

            def _stage_character_sheet_v2_source(self, source):
                return Staged()

            def _generate_krea_identity_edit(self, request, model, **context):
                calls.append(("base", dict(context)))
                return {
                    "PromptId": "base-prompt",
                    "ImagePath": "base.png",
                    "HistoryPath": "base.json",
                    "ModelId": "krea",
                    "ModelName": "Krea 2 Turbo",
                    "Seed": 123,
                    "GenerationSeconds": 8.0,
                }

            def _release_character_sheet_runtime(self):
                calls.append(("free",))
                return True

            def _persist_character_sheet_v2_base_metadata(self, result, metadata):
                calls.append(("base-metadata",))

            def _extract_v2_panels(self, base_path):
                calls.append(("extract", str(base_path)))
                return _panels()

            def _refine_v2_panel(self, request, model, panel, source):
                calls.append(("refine", panel.role))
                if panel.role == "back":
                    return {
                        "role": panel.role,
                        "path": panel.path,
                        "detailerStatus": "skipped",
                        "detailerSkipped": "back-view",
                    }
                return {
                    "role": panel.role,
                    "path": Path(f"{panel.role}-detailed.png"),
                    "detailerStatus": "completed",
                    "detailerSkipped": None,
                    "detailerPromptId": f"detail-{panel.index}",
                    "detailerHistoryPath": f"detail-{panel.index}.json",
                    "detailerGenerationSeconds": 1.0,
                }

            def _reassemble_v2_panels(self, base_path, panels):
                calls.append(("compose", [panel.path.name for panel in panels]))
                return Path("final.png")

            def _persist_character_sheet_v2(self, request, base_result, final_path, detail_results):
                calls.append(("persist-final", str(final_path)))
                if fail_persist:
                    raise sheetv2.base.StableAmdBridgeError("disk full")
                return {
                    "PromptId": "final-prompt",
                    "Mode": "character-sheet",
                    "EditOperation": "character-sheet-v2",
                    "ImagePath": str(final_path),
                    "HistoryPath": "final.json",
                    "CharacterSheetVersion": "v2-identity-edit",
                    "CharacterSheetItems": list(detail_results),
                }

            def _hide_character_sheet_v2_intermediates(self, base_result, detail_results, final_result):
                calls.append(("hide-intermediates", final_result["PromptId"]))

            def generate(self, request):
                return {"legacy": True}

        class Bridge(sheetv2.CharacterSheetV2BridgeMixin, Parent):
            # These are deliberate test seams. CharacterSheetV2BridgeMixin owns
            # the real implementations, so assign the fixture methods directly
            # on the concrete bridge to ensure the orchestration test never
            # imports runtime-only Pillow/DWPose code.
            _stage_character_sheet_v2_source = Parent._stage_character_sheet_v2_source
            _persist_character_sheet_v2_base_metadata = Parent._persist_character_sheet_v2_base_metadata
            _extract_v2_panels = Parent._extract_v2_panels
            _refine_v2_panel = Parent._refine_v2_panel
            _reassemble_v2_panels = Parent._reassemble_v2_panels
            _persist_character_sheet_v2 = Parent._persist_character_sheet_v2
            _hide_character_sheet_v2_intermediates = Parent._hide_character_sheet_v2_intermediates

        return Bridge()

    def test_detailer_runs_serially_composes_persists_then_hides_intermediates(self):
        calls = []
        result = self._bridge(calls).generate_character_sheet_v2(dict(BASE_REQUEST))

        self.assertEqual(result["ImagePath"], "final.png")
        self.assertEqual(result["EditOperation"], "character-sheet-v2")
        self.assertEqual([call[1] for call in calls if call[0] == "refine"], [
            "face", "front", "three-quarter", "side", "back"
        ])
        self.assertEqual(len([call for call in calls if call[0] == "base"]), 1)
        self.assertLess(
            next(i for i, call in enumerate(calls) if call[0] == "persist-final"),
            next(i for i, call in enumerate(calls) if call[0] == "hide-intermediates"),
        )
        self.assertIn(("free",), calls)

    def test_final_persistence_failure_keeps_intermediates_visible(self):
        calls = []
        with self.assertRaisesRegex(sheetv2.base.StableAmdBridgeError, "disk full"):
            self._bridge(calls, fail_persist=True).generate_character_sheet_v2(dict(BASE_REQUEST))
        self.assertFalse(any(call[0] == "hide-intermediates" for call in calls))

    def test_detailer_false_keeps_single_base_job_without_panel_pipeline(self):
        calls = []
        result = self._bridge(calls).generate_character_sheet_v2({**BASE_REQUEST, "characterSheetDetailer": False})
        self.assertEqual(result["EditOperation"], "character-sheet-v2-base")
        self.assertFalse(any(call[0] in {"extract", "refine", "compose", "persist-final", "hide-intermediates"} for call in calls))


if __name__ == "__main__":
    unittest.main()
