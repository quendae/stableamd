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

    def test_startup_controller_waits_for_model_metadata_and_ui_or_30_second_fallback(self):
        source = (FRONTEND / "app-startup.js").read_text(encoding="utf-8")
        self.assertIn("30000", source)
        self.assertIn("Promise.allSettled", source)
        self.assertIn('fetch("/api/models"', source)
        self.assertIn('fetch("/api/model-support"', source)
        self.assertIn('fetch("/api/generation-options"', source)
        self.assertIn('fetch("/api/lora-catalog"', source)
        self.assertIn("waitForUiReady", source)
        self.assertIn("startup-gate", source)
        self.assertIn("app-shell", source)

    def test_startup_styles_cover_screen_until_gate_releases(self):
        source = (FRONTEND / "extras.css").read_text(encoding="utf-8")
        self.assertIn(".startup-gate", source)
        self.assertIn("position: fixed", source)
        self.assertIn(".startup-spinner", source)


if __name__ == "__main__":
    unittest.main()
