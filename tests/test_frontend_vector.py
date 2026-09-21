from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "app" / "frontend"


class StableAmdVectorFrontendTests(unittest.TestCase):
    def _read(self, name: str) -> str:
        return (FRONTEND / name).read_text(encoding="utf-8")

    def test_index_exposes_dedicated_vector_navigation_workspace_and_assets(self):
        index = self._read("index.html")
        self.assertIn('data-page="vector"', index)
        self.assertIn('id="page-vector"', index)
        self.assertIn('id="vector-form"', index)
        for control in (
            "vector-prompt",
            "vector-style",
            "vector-detail",
            "vector-colors",
            "vector-background",
            "vector-background-color",
            "vector-seed",
            "vector-generate",
            "vector-dependency",
            "vector-install",
            "vector-result",
        ):
            self.assertIn(f'id="{control}"', index)
        self.assertIn('href="/vector.css"', index)
        self.assertIn('src="/app-vector.js"', index)

    def test_vector_module_uses_dedicated_api_and_shared_job_waiter_only(self):
        source = self._read("app-vector.js")
        for route in (
            "/api/vector/dependency",
            "/api/vector/install",
            "/api/vector/text-to-svg",
            "/api/vector/source?path=",
        ):
            self.assertIn(route, source)
        self.assertIn("StableAmdJobs.waitForGenerationJob", source)
        self.assertNotIn("asyncJob", source)
        for raster_control in ("sampler", "scheduler", "lora", "controlnet"):
            self.assertNotIn(raster_control, source.lower())

    def test_generation_jobs_exports_waiter_without_changing_vector_requests(self):
        source = self._read("app-generation-jobs.js")
        self.assertIn("window.StableAmdJobs", source)
        self.assertIn("waitForGenerationJob", source)
        self.assertIn('path === "/api/generate"', source)
        self.assertNotIn('path === "/api/vector/text-to-svg"', source)

    def test_vector_result_uses_preview_source_blob_and_safe_text_rendering(self):
        source = self._read("app-vector.js")
        self.assertIn("previewPath", source)
        self.assertIn("imageUrl", source)
        self.assertIn('new Blob([payload.svg], { type: "image/svg+xml;charset=utf-8" })', source)
        self.assertIn("textContent = payload.svg", source)
        self.assertNotIn("innerHTML", source)
        self.assertIn("URL.revokeObjectURL", source)
        self.assertIn("window.StableAmdVector", source)
        self.assertIn("loadRecord", source)

    def test_app_page_metadata_and_gallery_are_vector_aware(self):
        source = self._read("app.js")
        self.assertIn('vector: ["Vector", "Create clean editable SVG assets from text prompts."]', source)
        self.assertIn("assetType", source)
        self.assertIn("previewPath", source)
        self.assertIn("SVG", source)

    def test_post_actions_replace_raster_actions_for_svg_records(self):
        source = self._read("app-post-actions.js")
        self.assertIn("assetType", source)
        self.assertIn('=== "svg"', source)
        for action in ("vector-download", "vector-source", "vector-reuse", "delete"):
            self.assertIn(action, source)
        self.assertIn("StableAmdVector.loadRecord", source)
        self.assertIn('setPage("vector")', source)

    def test_vector_styles_use_two_column_desktop_one_column_existing_breakpoint_and_six_mobile_nav_items(self):
        vector_css = self._read("vector.css")
        styles = self._read("styles.css")
        self.assertIn(".vector-layout", vector_css)
        self.assertIn("grid-template-columns", vector_css)
        self.assertIn("@media (max-width: 980px)", vector_css)
        self.assertIn("grid-template-columns: 1fr", vector_css)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr))", styles)


if __name__ == "__main__":
    unittest.main()
