from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_svg_preview as preview

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"stableamd-preview"


class SvgPreviewTests(unittest.TestCase):
    def test_render_writes_resvg_png_atomically(self):
        calls = []
        fake = types.ModuleType("resvg_py")

        def svg_to_bytes(*, svg_string):
            calls.append(svg_string)
            return PNG_BYTES

        fake.svg_to_bytes = svg_to_bytes
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"resvg_py": fake}):
            output = Path(tmp) / "asset-preview.png"
            result = preview.render_svg_preview(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0L10 0L10 10Z"/></svg>',
                output,
            )
            self.assertEqual(result, output.resolve())
            self.assertEqual(output.read_bytes(), PNG_BYTES)
            self.assertEqual(len(calls), 1)
            self.assertFalse(any(".tmp-" in item.name for item in output.parent.iterdir()))

    def test_render_rejects_empty_or_non_png_renderer_output(self):
        for payload in (b"", b"not-a-png", None):
            fake = types.ModuleType("resvg_py")
            fake.svg_to_bytes = lambda **kwargs: payload
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"resvg_py": fake}):
                output = Path(tmp) / "asset-preview.png"
                with self.assertRaisesRegex(preview.base.StableAmdBridgeError, "PNG"):
                    preview.render_svg_preview("<svg/>", output)
                self.assertFalse(output.exists())

    def test_render_rejects_empty_svg_source(self):
        fake = types.ModuleType("resvg_py")
        fake.svg_to_bytes = lambda **kwargs: PNG_BYTES
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"resvg_py": fake}):
            with self.assertRaisesRegex(preview.base.StableAmdBridgeError, "SVG"):
                preview.render_svg_preview("   ", Path(tmp) / "preview.png")

    def test_missing_renderer_has_actionable_error(self):
        real_import = __import__

        def guarded_import(name, *args, **kwargs):
            if name == "resvg_py":
                raise ImportError("synthetic missing package")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, mock.patch("builtins.__import__", side_effect=guarded_import):
            with self.assertRaisesRegex(preview.base.StableAmdBridgeError, "Install the Vector dependency"):
                preview.render_svg_preview("<svg/>", Path(tmp) / "preview.png")


if __name__ == "__main__":
    unittest.main()
