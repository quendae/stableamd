from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_server as base
import stableamd_v03_vector as vector


class _ApiParent:
    def __init__(self, bridge):
        self.bridge = bridge

    def dispatch(self, method, target, body=None):
        return 404, {"error": "not found"}


class _VectorSourceApi(vector.VectorApiMixin, _ApiParent):
    pass


class _VectorSourceBridge:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()

    vector_source = vector.VectorBridgeMixin.vector_source


class VectorAssetSafetyTests(unittest.TestCase):
    def _layout(self, temporary: str):
        repo_root = Path(temporary).resolve()
        output_root = repo_root / ".runtime" / "stableamd" / "output"
        vector_root = output_root / "vector"
        history_root = repo_root / ".runtime" / "stableamd" / "history"
        vector_root.mkdir(parents=True)
        history_root.mkdir(parents=True)
        return repo_root, output_root, vector_root, history_root

    def test_resolve_output_svg_accepts_only_existing_svg_inside_vector_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root, output_root, vector_root, _history_root = self._layout(temporary)
            svg = vector_root / "asset.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h1v1z"/></svg>', encoding="utf-8")

            self.assertEqual(base.resolve_output_svg(repo_root, str(svg)), svg.resolve())

            png = vector_root / "asset.png"
            png.write_bytes(b"png")
            outside_vector = output_root / "outside.svg"
            outside_vector.write_text("<svg/>", encoding="utf-8")
            external = repo_root / "external.svg"
            external.write_text("<svg/>", encoding="utf-8")

            rejected = [
                str(png),
                str(vector_root / "missing.svg"),
                str(vector_root),
                str(vector_root / ".." / "outside.svg"),
                str(outside_vector),
                str(external),
            ]
            for requested in rejected:
                with self.subTest(requested=requested):
                    with self.assertRaises(ValueError):
                        base.resolve_output_svg(repo_root, requested)

    def test_vector_source_requires_persisted_sanitized_history_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root, _output_root, vector_root, history_root = self._layout(temporary)
            svg = vector_root / "persisted.svg"
            source = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h1v1z"/></svg>'
            svg.write_text(source, encoding="utf-8")
            api = _VectorSourceApi(_VectorSourceBridge(repo_root))
            target = "/api/vector/source?path=" + quote(str(svg))

            code, payload = api.dispatch("GET", target)
            self.assertNotEqual(code, 200)

            history = history_root / "vector.json"
            history.write_text(
                json.dumps({
                    "promptId": "vector-1",
                    "assetType": "svg",
                    "sanitized": True,
                    "svgPath": str(svg),
                    "previewPath": str(vector_root / "persisted-preview.png"),
                }),
                encoding="utf-8",
            )

            code, payload = api.dispatch("GET", target)
            self.assertEqual(code, 200)
            self.assertEqual(payload, {"fileName": "persisted.svg", "svg": source})

    def test_vector_source_rejects_unsanitized_or_mismatched_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo_root, _output_root, vector_root, history_root = self._layout(temporary)
            svg = vector_root / "asset.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1z"/></svg>', encoding="utf-8")
            api = _VectorSourceApi(_VectorSourceBridge(repo_root))
            target = "/api/vector/source?path=" + quote(str(svg))

            for index, record in enumerate((
                {"assetType": "svg", "sanitized": False, "svgPath": str(svg)},
                {"assetType": "svg", "sanitized": True, "svgPath": str(vector_root / "other.svg")},
                {"assetType": "png", "sanitized": True, "svgPath": str(svg)},
            )):
                history = history_root / f"bad-{index}.json"
                history.write_text(json.dumps(record), encoding="utf-8")

            code, _payload = api.dispatch("GET", target)
            self.assertNotEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
