from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_svg_sanitize as sanitize


class CleanSvgSanitizerTests(unittest.TestCase):
    def test_valid_basic_geometry_is_normalized_deterministically(self):
        source = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
            '<g opacity="0.8"><path stroke-linejoin="round" fill="#ff0000" d="M0 0 L64 0 L64 64 Z"/>'
            '<rect y="10" x="10" width="12" height="8" fill="#00ff00"/></g></svg>'
        )
        first = sanitize.sanitize_svg(source)
        second = sanitize.sanitize_svg(source)
        self.assertEqual(first.xml, second.xml)
        self.assertEqual(first.width, 64)
        self.assertEqual(first.height, 64)
        self.assertEqual(first.path_count, 1)
        self.assertGreaterEqual(first.node_count, 4)
        self.assertIn('viewBox="0 0 64 64"', first.xml)
        self.assertIn('<path', first.xml)
        self.assertIn('<rect', first.xml)
        self.assertNotIn('script', first.xml.lower())

    def test_numeric_dimensions_can_supply_missing_viewbox(self):
        clean = sanitize.sanitize_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200">'
            '<circle cx="100" cy="100" r="40" fill="#123456"/></svg>'
        )
        self.assertEqual((clean.width, clean.height), (320, 200))
        self.assertIn('viewBox="0 0 320 200"', clean.xml)

    def test_rejects_malformed_dtd_and_entity_documents(self):
        bad_documents = [
            '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg',
            '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0L1 1"/></svg>',
            '<!DOCTYPE svg [<!ENTITY x "boom">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0L1 1"/></svg>',
        ]
        for document in bad_documents:
            with self.subTest(document=document[:30]):
                with self.assertRaises(sanitize.SvgSanitizationError):
                    sanitize.sanitize_svg(document)

    def test_rejects_forbidden_elements(self):
        elements = [
            '<script>alert(1)</script>',
            '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>',
            '<image href="data:image/png;base64,AA=="/>',
            '<text>x</text>',
            '<tspan>x</tspan>',
            '<filter id="f"/>',
            '<mask id="m"/>',
            '<clipPath id="c"/>',
            '<animate attributeName="x" dur="1s"/>',
            '<use href="#shape"/>',
        ]
        for element in elements:
            document = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                '<path d="M0 0L10 0L10 10Z"/>' + element + '</svg>'
            )
            with self.subTest(element=element.split('>')[0]):
                with self.assertRaises(sanitize.SvgSanitizationError):
                    sanitize.sanitize_svg(document)

    def test_rejects_event_href_url_and_unknown_attributes(self):
        attributes = [
            'onclick="alert(1)"',
            'href="https://example.com/x.svg"',
            'xlink:href="https://example.com/x.svg" xmlns:xlink="http://www.w3.org/1999/xlink"',
            'fill="url(https://example.com/a.svg#p)"',
            'style="fill:red"',
            'class="external-style"',
        ]
        for attribute in attributes:
            document = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                f'<path d="M0 0L10 0L10 10Z" {attribute}/></svg>'
            )
            with self.subTest(attribute=attribute):
                with self.assertRaises(sanitize.SvgSanitizationError):
                    sanitize.sanitize_svg(document)

    def test_rejects_unknown_namespace_and_unknown_element(self):
        documents = [
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:evil="https://evil.test/ns" viewBox="0 0 10 10">'
            '<evil:path d="M0 0L10 10"/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path xmlns="https://evil.test/ns" d="M0 0L1 1"/></svg>',
        ]
        for document in documents:
            with self.assertRaises(sanitize.SvgSanitizationError):
                sanitize.sanitize_svg(document)

    def test_rejects_invalid_or_nonfinite_geometry(self):
        viewboxes = [
            "0 0 0 10",
            "0 0 -1 10",
            "0 0 NaN 10",
            "0 0 inf 10",
            "0 0 10",
            "hello world",
        ]
        for viewbox in viewboxes:
            document = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">'
                '<path d="M0 0L1 1"/></svg>'
            )
            with self.subTest(viewbox=viewbox):
                with self.assertRaises(sanitize.SvgSanitizationError):
                    sanitize.sanitize_svg(document)

        for dimension in ['100%', '10px', '-1', 'NaN']:
            document = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{dimension}" height="10">'
                '<path d="M0 0L1 1"/></svg>'
            )
            with self.subTest(dimension=dimension):
                with self.assertRaises(sanitize.SvgSanitizationError):
                    sanitize.sanitize_svg(document)

    def test_rejects_document_without_drawable_geometry(self):
        for document in [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><g/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d=""/></svg>',
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="0" height="4"/></svg>',
        ]:
            with self.subTest(document=document):
                with self.assertRaises(sanitize.SvgSanitizationError):
                    sanitize.sanitize_svg(document)

    def test_removes_metadata_comments_and_empty_groups_but_preserves_drawable_shapes(self):
        document = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<metadata>producer</metadata><!-- producer comment --><g></g>'
            '<g><circle cx="5" cy="5" r="2" fill="#fff"/></g></svg>'
        )
        clean = sanitize.sanitize_svg(document)
        self.assertNotIn('producer', clean.xml)
        self.assertNotIn('metadata', clean.xml)
        self.assertEqual(clean.xml.count('<g'), 1)
        self.assertIn('<circle', clean.xml)

    def test_enforces_source_bytes_node_and_path_limits(self):
        one_path = '<path d="M0 0L1 1"/>'
        document = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' + one_path * 3 + '</svg>'
        with self.assertRaisesRegex(sanitize.SvgSanitizationError, "path"):
            sanitize.sanitize_svg(document, max_paths=2)
        with self.assertRaisesRegex(sanitize.SvgSanitizationError, "node"):
            sanitize.sanitize_svg(document, max_nodes=3)
        with self.assertRaisesRegex(sanitize.SvgSanitizationError, "size"):
            sanitize.sanitize_svg(document, max_bytes=16)

    def test_accepts_supported_shape_geometry_and_presentation_attributes(self):
        document = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<line x1="1" y1="2" x2="3" y2="4" stroke="#000" stroke-width="2" stroke-linecap="round"/>'
            '<ellipse cx="20" cy="30" rx="5" ry="8" fill="#fff" fill-opacity="0.5"/>'
            '<polygon points="0,0 10,0 5,8" fill="none" stroke="#123" stroke-linejoin="bevel"/>'
            '<polyline points="0,20 10,30 20,20" opacity="0.7"/>'
            '<rect x="30" y="40" width="20" height="10" rx="2" ry="2" transform="translate(1 2)"/>'
            '</svg>'
        )
        clean = sanitize.sanitize_svg(document)
        for tag in ('line', 'ellipse', 'polygon', 'polyline', 'rect'):
            self.assertIn(f'<{tag}', clean.xml)


if __name__ == "__main__":
    unittest.main()
