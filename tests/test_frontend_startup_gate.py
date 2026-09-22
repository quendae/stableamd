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

    def test_startup_controller_waits_for_model_ui_and_v03_critical_barrier(self):
        source = (FRONTEND / "app-startup.js").read_text(encoding="utf-8")
        self.assertIn("15000", source)
        self.assertIn("450", source)
        self.assertIn("state.models", source)
        self.assertNotIn('fetch("/api/models"', source)
        self.assertIn('fetchJson("/api/model-support"', source)
        self.assertIn("waitForModelUiReady", source)
        self.assertIn("waitForCriticalStartup", source)
        self.assertIn("window.StableAmdStartup", source)
        self.assertIn("markCriticalReady", source)
        self.assertIn("startup-gate", source)
        self.assertIn("app-shell", source)

        # Generation options and LoRA metadata continue loading in the background;
        # they must not extend the critical Generate-ready startup barrier.
        self.assertNotIn('fetch("/api/generation-options"', source)
        self.assertNotIn('fetch("/api/lora-catalog"', source)
        self.assertNotIn("generationOptionsUiReady", source)
        self.assertNotIn("loraUiReady", source)

    def test_v03_marks_critical_startup_ready_only_after_models_and_support_settle(self):
        source = (FRONTEND / "app-v03.js").read_text(encoding="utf-8")
        self.assertIn("markCriticalReady", source)
        self.assertIn("refreshModelPackages", source)
        self.assertIn("refreshExecutionSupport", source)
        self.assertIn("Promise.allSettled", source)

    def test_startup_styles_cover_screen_until_gate_releases(self):
        source = (FRONTEND / "extras.css").read_text(encoding="utf-8")
        self.assertIn(".startup-gate", source)
        self.assertIn("position: fixed", source)
        self.assertIn(".startup-spinner", source)


if __name__ == "__main__":
    unittest.main()
