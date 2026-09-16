from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "app" / "frontend"


class StableAmdFrontendStartupGateTests(unittest.TestCase):
    def test_index_starts_with_loading_gate_and_loads_controller_before_app(self):
        source = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="startup-gate"', source)
        self.assertIn('Loading models', source)
        self.assertIn('class="app-shell" hidden', source)
        startup = source.index('src="/app-startup.js"')
        app = source.index('src="/app.js"')
        self.assertLess(startup, app)

    def test_startup_controller_waits_only_for_supported_model_list_or_10_second_fallback(self):
        source = (FRONTEND / "app-startup.js").read_text(encoding="utf-8")
        self.assertIn("10000", source)
        self.assertIn("state.models", source)
        self.assertNotIn('fetch("/api/models"', source)
        self.assertIn('fetch("/api/model-support"', source)
        self.assertIn("waitForModelUiReady", source)
        self.assertIn("startup-gate", source)
        self.assertIn("app-shell", source)

        # Generation options and LoRA metadata continue loading in the background;
        # they must not extend the model-list startup gate.
        self.assertNotIn('fetch("/api/generation-options"', source)
        self.assertNotIn('fetch("/api/lora-catalog"', source)
        self.assertNotIn("generationOptionsUiReady", source)
        self.assertNotIn("loraUiReady", source)

    def test_startup_styles_cover_screen_until_gate_releases(self):
        source = (FRONTEND / "extras.css").read_text(encoding="utf-8")
        self.assertIn(".startup-gate", source)
        self.assertIn("position: fixed", source)
        self.assertIn(".startup-spinner", source)


if __name__ == "__main__":
    unittest.main()
