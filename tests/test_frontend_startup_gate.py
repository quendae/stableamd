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
        startup = source.index('src="/app-startup.js"')
        app = source.index('src="/app.js"')
        self.assertLess(startup, app)

    def test_startup_controller_reveals_gui_after_tasks_or_30_second_fallback(self):
        source = (FRONTEND / "app-startup.js").read_text(encoding="utf-8")
        self.assertIn("30000", source)
        self.assertIn("Promise.allSettled", source)
        self.assertIn("startup-gate", source)
        self.assertIn("app-shell", source)
        self.assertIn("track", source)

    def test_initial_model_and_option_loaders_are_registered_with_gate(self):
        app = (FRONTEND / "app.js").read_text(encoding="utf-8")
        v02 = (FRONTEND / "app-v02.js").read_text(encoding="utf-8")
        compat = (FRONTEND / "app-lora-compat.js").read_text(encoding="utf-8")
        v03 = (FRONTEND / "app-v03.js").read_text(encoding="utf-8")

        self.assertIn('stableAmdStartup.track("base-models"', app)
        self.assertIn('stableAmdStartup.track("generation-options"', v02)
        self.assertIn('stableAmdStartup.track("lora-catalog"', compat)
        self.assertIn('stableAmdStartup.track("v03-model-packages"', v03)


if __name__ == "__main__":
    unittest.main()
