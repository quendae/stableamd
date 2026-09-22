from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_PATH = ROOT / "app" / "frontend" / "app-krea-edit.js"


class CharacterSheetV2FrontendTests(unittest.TestCase):
    def test_v2_ui_exposes_identity_dependency_description_and_acceptance_version(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        for expected in (
            "Character Sheet v2 · Identity Edit",
            "Character description",
            'id="krea-character-description"',
            'maxlength="600"',
            'id="krea-character-sheet-version"',
            'value="v2"',
            'value="legacy-sequential"',
            "/api/krea-identity/dependency",
            "/api/krea-identity/install",
            "Install Identity Edit",
            "Installed — restart StableAMD to activate",
            "Base sheet",
            "Face detail",
            "Final compose",
        ):
            self.assertIn(expected, source)

    def test_v2_hides_backend_owned_geometry_and_gates_generate_on_dependency(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn('document.querySelector("#width")', source)
        self.assertIn('document.querySelector("#height")', source)
        self.assertIn("widthField.hidden = v2Active", source)
        self.assertIn("heightField.hidden = v2Active", source)
        self.assertIn("generateButton.disabled = v2Active && !identityDependency.ready", source)
        self.assertIn("legacyFraming.hidden = !legacyActive", source)

    def test_result_summary_reports_v2_identity_and_panel_detail_status(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        self.assertIn("v2 · Identity Edit", source)
        self.assertIn("detailerStatus", source)
        self.assertIn("detailerSkipped", source)
        self.assertIn("CharacterSheetItems", source)


if __name__ == "__main__":
    unittest.main()
