from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_svg_sanitize as sanitize


class VTracerSvgCompatibilityTests(unittest.TestCase):
    def test_accepts_vtracer_svg_11_root_version_and_strips_it_from_clean_svg(self):
        source = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- Generator: visioncortex VTracer 1.0.0-alpha.4 -->\n'
            '<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="48" height="48">'
            '<path d="M0,0L48,0L48,48L0,48Z" fill="#ff0000"/>'
            '</svg>'
        )

        clean = sanitize.sanitize_svg(source)

        self.assertEqual((clean.width, clean.height), (48, 48))
        self.assertIn('viewBox="0 0 48 48"', clean.xml)
        self.assertIn('<path', clean.xml)
        self.assertNotIn('version=', clean.xml)

    def test_rejects_unknown_svg_root_version(self):
        source = (
            '<svg version="9.9" xmlns="http://www.w3.org/2000/svg" width="48" height="48">'
            '<path d="M0,0L48,0L48,48L0,48Z" fill="#ff0000"/>'
            '</svg>'
        )

        with self.assertRaises(sanitize.SvgSanitizationError):
            sanitize.sanitize_svg(source)


if __name__ == "__main__":
    unittest.main()
