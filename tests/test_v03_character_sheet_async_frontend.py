from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_PATH = ROOT / "app" / "frontend" / "app-krea-edit.js"


class StableAmdCharacterSheetAsyncFrontendTests(unittest.TestCase):
    def test_character_sheet_v2_submits_one_backend_owned_async_job(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")

        self.assertIn("waitForCharacterSheetGenerationJob", source)
        self.assertIn("/api/generation-jobs/${encoded}/result", source)
        self.assertIn("async function submitCharacterSheetJob", source)
        self.assertIn("waitForCharacterSheetGenerationJob(jobId)", source)
        self.assertIn("const v2Payload = {", source)
        self.assertIn('characterSheetVersion: "v2"', source)
        self.assertIn("characterSheetDetailer: true", source)
        self.assertIn("asyncJob: true", source)
        self.assertIn("delete v2Payload.width", source)
        self.assertIn("delete v2Payload.height", source)
        self.assertIn("await submitCharacterSheetJob(path, options, v2Payload)", source)
        self.assertIn("Character Sheet v2 · generating", source)

    def test_legacy_sequential_loop_is_explicitly_isolated(self):
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        marker = "async function runLegacyCharacterSheet"
        self.assertIn(marker, source)
        start = source.index(marker)
        api_start = source.index("api = async function kreaImageEditApi")
        legacy_source = source[start:api_start]
        self.assertIn("for (const view of CHARACTER_SHEET_VIEWS)", legacy_source)
        self.assertIn('characterSheetPhase: "identity-refine"', legacy_source)
        self.assertIn('/api/character-sheet/compose', legacy_source)

        v2_start = source.index("async function runCharacterSheetV2")
        v2_source = source[v2_start:start]
        self.assertNotIn("for (const view of CHARACTER_SHEET_VIEWS)", v2_source)
        self.assertNotIn('/api/character-sheet/compose', v2_source)


if __name__ == "__main__":
    unittest.main()
