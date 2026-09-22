from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_server as base
import stableamd_v03_svg_sanitize as svg_sanitize
import stableamd_v03_vector as vector


class Parent:
    def generate(self, request):
        raise AssertionError("probe overrides child raster generation")


class OrchestrationProbe(vector.VectorBridgeMixin, Parent):
    def __init__(self, repo_root: Path, *, fail_at: str | None = None):
        self.repo_root = Path(repo_root)
        self.calls: list[str] = []
        self.fail_at = fail_at
        self.raster_history_hidden = False
        self.raster = self.repo_root / ".runtime" / "stableamd" / "output" / "raster.png"
        self.raster.parent.mkdir(parents=True, exist_ok=True)
        self.raster.write_bytes(b"not-decoded-by-probe")
        self.raster_history = self.repo_root / ".runtime" / "stableamd" / "history" / "raster.json"
        self.raster_history.parent.mkdir(parents=True, exist_ok=True)
        self.raster_history.write_text('{"galleryHidden": false}', encoding="utf-8")

    def _vector_dependency_ready(self):
        self.calls.append("dependency-ready")
        return True

    def _select_vector_model(self):
        self.calls.append("select-zimage")
        return {"id": "z", "family": "z-image-turbo", "name": "Z-Image Turbo"}

    def _build_vector_prompt(self, request):
        self.calls.append("build-prompt")
        return "effective vector prompt"

    def _generate_vector_raster(self, request, model, prompt):
        self.calls.append("generate-raster")
        return {
            "PromptId": "raster-prompt",
            "ImagePath": str(self.raster),
            "HistoryPath": str(self.raster_history),
            "Seed": 123,
            "ModelId": "z",
            "ModelName": "Z-Image Turbo",
            "GenerationSeconds": 1.25,
        }

    def _release_vector_runtime(self):
        self.calls.append("release-runtime")
        return True

    def _prepare_vector_raster_file(self, source_path, destination_path, background):
        self.calls.append("prepare-raster")
        Path(destination_path).write_bytes(b"prepared")
        return Path(destination_path)

    def _run_vectorizer(self, prepared_path, raw_svg_path, request):
        self.calls.append("vtracer")
        if self.fail_at == "vtracer":
            raise base.StableAmdBridgeError("synthetic vectorizer failure")
        Path(raw_svg_path).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0L16 0L16 16Z"/></svg>', encoding="utf-8")
        return Path(raw_svg_path)

    def _sanitize_vector_svg(self, raw_svg_path):
        self.calls.append("sanitize")
        if self.fail_at == "sanitize":
            raise base.StableAmdBridgeError("synthetic sanitize failure")
        return svg_sanitize.SanitizedSvg(
            xml='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M0 0L16 0L16 16Z"/></svg>',
            width=16,
            height=16,
            node_count=2,
            path_count=1,
        )

    def _render_vector_preview(self, svg_text, preview_path):
        self.calls.append("preview")
        if self.fail_at == "preview":
            raise base.StableAmdBridgeError("synthetic preview failure")
        Path(preview_path).write_bytes(b"preview")
        return Path(preview_path)

    def _persist_vector_history(self, record):
        self.calls.append("persist")
        if self.fail_at == "persist":
            raise base.StableAmdBridgeError("synthetic persistence failure")
        path = self.repo_root / ".runtime" / "stableamd" / "history" / "vector.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def _hide_vector_raster_history(self, raster_result, vector_prompt_id, preview_path):
        self.calls.append("hide-intermediate")
        self.raster_history_hidden = True


class VectorOrchestrationTests(unittest.TestCase):
    def test_pipeline_order_releases_gpu_before_vtracer_and_hides_after_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = OrchestrationProbe(Path(tmp))
            result = bridge.text_to_svg({
                "prompt": "fox mark",
                "style": "icon",
                "detail": "medium",
                "colors": 4,
                "background": "transparent",
                "seed": 123,
            })

            self.assertEqual(bridge.calls, [
                "dependency-ready",
                "select-zimage",
                "build-prompt",
                "generate-raster",
                "release-runtime",
                "prepare-raster",
                "vtracer",
                "sanitize",
                "preview",
                "persist",
                "hide-intermediate",
            ])
            self.assertLess(bridge.calls.index("release-runtime"), bridge.calls.index("vtracer"))
            self.assertGreater(bridge.calls.index("hide-intermediate"), bridge.calls.index("persist"))
            self.assertTrue(bridge.raster_history_hidden)
            self.assertEqual(result["assetType"], "svg")
            self.assertEqual(result["provider"], "zimage-vtrace")
            self.assertEqual(result["width"], 16)
            self.assertEqual(result["height"], 16)
            self.assertEqual(result["pathCount"], 1)
            self.assertEqual(result["nodeCount"], 2)
            self.assertTrue(result["sanitized"])
            self.assertEqual(result["seed"], 123)
            self.assertTrue(Path(result["svgPath"]).is_file())
            self.assertTrue(Path(result["previewPath"]).is_file())
            self.assertTrue(Path(result["historyPath"]).is_file())
            vector_root = Path(tmp) / ".runtime" / "stableamd" / "output" / "vector"
            self.assertFalse(any(path.name.endswith(".raw.svg") for path in vector_root.iterdir()))
            self.assertFalse(any("prepared" in path.name for path in vector_root.iterdir()))

    def test_failure_after_raster_keeps_child_visible_and_never_reports_svg_success(self):
        for stage in ("vtracer", "sanitize", "preview", "persist"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                bridge = OrchestrationProbe(Path(tmp), fail_at=stage)
                with self.assertRaises(base.StableAmdBridgeError):
                    bridge.text_to_svg({"prompt": "fox", "background": "transparent"})
                self.assertFalse(bridge.raster_history_hidden)
                self.assertNotIn("hide-intermediate", bridge.calls)
                vector_root = Path(tmp) / ".runtime" / "stableamd" / "output" / "vector"
                if vector_root.exists():
                    self.assertFalse(any(path.suffix.lower() == ".svg" for path in vector_root.iterdir()))
                    self.assertFalse(any(path.name.endswith("-preview.png") for path in vector_root.iterdir()))
                self.assertTrue(bridge.raster.is_file())
                self.assertTrue(bridge.raster_history.is_file())

    def test_missing_dependency_fails_before_model_or_raster_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = OrchestrationProbe(Path(tmp))
            bridge._vector_dependency_ready = lambda: False
            with self.assertRaisesRegex(base.StableAmdBridgeError, "Vector dependency"):
                bridge.text_to_svg({"prompt": "fox"})
            self.assertEqual(bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
