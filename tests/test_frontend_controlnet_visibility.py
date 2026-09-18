from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class StableAmdControlVisibilityTests(unittest.TestCase):
    def test_hidden_control_grids_are_not_forced_visible_by_grid_css(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-controlnet.js").read_text(encoding="utf-8")

        self.assertIn("canny.hidden = !enabled.checked || type.value !== 'canny';", source)
        self.assertIn(".controlnet-grid[hidden] { display:none !important; }", source)


if __name__ == "__main__":
    unittest.main()
