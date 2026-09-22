from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POSE_EDITOR = REPO_ROOT / "app" / "frontend" / "app-pose-editor.js"


class StableAmdPoseRealisticGalleryTests(unittest.TestCase):
    def setUp(self):
        self.source = POSE_EDITOR.read_text(encoding="utf-8")

    def test_pose_templates_pair_realistic_preview_with_openpose_control_map(self):
        self.assertIn("previewUrl: `${POSE_DEPOT_ROOT}/${folder}/Cover.png`", self.source)
        self.assertIn("fallbackPreviewUrl: `${POSE_DEPOT_ROOT}/${folder}/Example.png`", self.source)
        self.assertIn("controlUrl: `${POSE_DEPOT_ROOT}/${folder}/OpenPoseFull.png`", self.source)

    def test_gallery_card_shows_realistic_preview_and_skeleton_badge(self):
        self.assertIn("pose-template-preview-wrap", self.source)
        self.assertIn("pose-template-preview", self.source)
        self.assertIn("pose-template-skeleton-badge", self.source)
        self.assertIn("src=\"${template.previewUrl}\"", self.source)
        self.assertIn("src=\"${template.controlUrl}\"", self.source)

    def test_selecting_gallery_pose_fetches_only_openpose_control_asset(self):
        self.assertIn("fetch(template.controlUrl", self.source)
        self.assertIn("state.selectedPreview = template.controlUrl", self.source)
        self.assertNotIn("fetch(template.previewUrl", self.source)

    def test_gallery_explains_preview_is_not_control_input(self):
        self.assertIn("realistic pose preview", self.source.lower())
        self.assertIn("openpose skeleton", self.source.lower())
        self.assertIn("actual control image", self.source.lower())


if __name__ == "__main__":
    unittest.main()
