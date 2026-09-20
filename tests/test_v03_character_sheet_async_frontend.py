from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_PATH = ROOT / "app" / "frontend" / "app-krea-edit.js"


class StableAmdCharacterSheetAsyncFrontendTests(unittest.TestCase):
    def test_character_sheet_waits_for_async_child_results_before_compose(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")

        self.assertIn("waitForCharacterSheetGenerationJob", source)
        self.assertIn("/api/generation-jobs/${encoded}/result", source)
        self.assertIn("async function submitCharacterSheetJob", source)
        self.assertIn("waitForCharacterSheetGenerationJob(jobId)", source)
        self.assertIn("viewPayload.asyncJob = true", source)
        self.assertIn("await submitCharacterSheetJob(path, options, viewPayload)", source)
        self.assertIn("Character Sheet child generation did not return an image path", source)


if __name__ == "__main__":
    unittest.main()
