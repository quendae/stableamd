from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import stableamd_server as base

SANITIZER_VERSION = "clean-svg-v1"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"

ALLOWED_TAGS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "polygon",
    "polyline",
    "line",
}
_REMOVABLE_TAGS = {"metadata"}

PRESENTATION_ATTRIBUTES = {
    "fill",
    "stroke",
    "stroke-width",
    "opacity",
    "fill-opacity",
    "stroke-opacity",
    "transform",
    "stroke-linecap",
    "stroke-linejoin",
}
GEOMETRY_ATTRIBUTES = {
    "svg": {"viewBox", "width", "height"},
    "g": set(),
    "path": {"d"},
    "rect": {"x", "y", "width", "height", "rx", "ry"},
    "circle": {"cx", "cy", "r"},
    "ellipse": {"cx", "cy", "rx", "ry"},
    "polygon": {"points"},
    "polyline": {"points"},
    "line": {"x1", "y1", "x2", "y2"},
}
_NUMERIC_GEOMETRY_ATTRIBUTES = {
    "x",
    "y",
    "width",
    "height",
    "rx",
    "ry",
    "cx",
    "cy",
    "r",
    "x1",
    "y1",
    "x2",
    "y2",
}
_DRAW_COMMAND_RE = re.compile(r"[LlHhVvCcSsQqTtAaZz]")
_SPLIT_NUMBERS_RE = re.compile(r"[\s,]+")
_FORBIDDEN_DECL_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_XML_STYLESHEET_RE = re.compile(r"<\?\s*xml-stylesheet\b", re.IGNORECASE)


class SvgSanitizationError(base.StableAmdBridgeError):
    pass


@dataclass(frozen=True)
class SanitizedSvg:
    xml: str
    width: int
    height: int
    node_count: int
    path_count: int


def _fail(message: str) -> None:
    raise SvgSanitizationError(message)


def _qualified_name(value: Any) -> tuple[str | None, str]:
    text = str(value)
    if text.startswith("{"):
        closing = text.find("}")
        if closing <= 1:
            _fail("SVG contains a malformed XML namespace.")
        return text[1:closing], text[closing + 1 :]
    return None, text


def _validate_namespace(namespace: str | None) -> None:
    if namespace not in {None, "", SVG_NAMESPACE}:
        _fail(f"SVG namespace '{namespace}' is not allowed by the Clean SVG contract.")


def _finite_number(value: Any, label: str) -> float:
    text = str(value or "").strip()
    if not text:
        _fail(f"SVG {label} must be a finite number.")
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise SvgSanitizationError(f"SVG {label} must be a finite number.") from exc
    if not math.isfinite(number):
        _fail(f"SVG {label} must be a finite number.")
    return number


def _positive_number(value: Any, label: str) -> float:
    number = _finite_number(value, label)
    if number <= 0:
        _fail(f"SVG {label} must be greater than zero.")
    return number


def _number_text(value: float) -> str:
    if value == 0 or abs(value) < 1e-12:
        return "0"
    if float(value).is_integer():
        return str(int(value))
    return format(value, ".12g")


def _parse_view_box(value: Any) -> tuple[float, float, float, float]:
    parts = [part for part in re.split(r"[\s,]+", str(value or "").strip()) if part]
    if len(parts) != 4:
        _fail("SVG viewBox must contain exactly four finite numbers.")
    numbers = tuple(_finite_number(part, "viewBox") for part in parts)
    if numbers[2] <= 0 or numbers[3] <= 0:
        _fail("SVG viewBox width and height must be greater than zero.")
    return numbers  # type: ignore[return-value]


def _normalized_root_geometry(root: ET.Element) -> tuple[str, str, str, int, int]:
    raw_view_box = root.attrib.get("viewBox")
    raw_width = root.attrib.get("width")
    raw_height = root.attrib.get("height")

    if raw_view_box is not None:
        x, y, view_width, view_height = _parse_view_box(raw_view_box)
        if raw_width is None:
            width = view_width
        else:
            width = _positive_number(raw_width, "width")
        if raw_height is None:
            height = view_height
        else:
            height = _positive_number(raw_height, "height")
    else:
        if raw_width is None or raw_height is None:
            _fail("SVG requires a finite viewBox or unambiguous numeric width and height.")
        width = _positive_number(raw_width, "width")
        height = _positive_number(raw_height, "height")
        x, y, view_width, view_height = 0.0, 0.0, width, height

    view_box = " ".join(_number_text(value) for value in (x, y, view_width, view_height))
    width_text = _number_text(width)
    height_text = _number_text(height)
    return view_box, width_text, height_text, max(1, int(round(width))), max(1, int(round(height)))


def _validate_document_namespaces(svg_text: str) -> None:
    try:
        for _, declaration in ET.iterparse(io.StringIO(svg_text), events=("start-ns",)):
            _prefix, uri = declaration
            _validate_namespace(uri)
    except SvgSanitizationError:
        raise
    except ET.ParseError as exc:
        raise SvgSanitizationError(f"SVG XML is malformed: {exc}") from exc


def _validate_attribute(tag: str, raw_name: str, raw_value: str) -> tuple[str, str]:
    namespace, name = _qualified_name(raw_name)
    _validate_namespace(namespace)
    lower_name = name.lower()
    value = str(raw_value).strip()

    if lower_name.startswith("on"):
        _fail(f"SVG event attribute '{name}' is forbidden.")
    if lower_name == "href" or lower_name.endswith(":href"):
        _fail("SVG href references are forbidden.")
    if "url(" in value.lower():
        _fail(f"SVG attribute '{name}' contains a forbidden URL reference.")
    if any(ord(character) < 0x20 and character not in "\t\r\n" for character in value):
        _fail(f"SVG attribute '{name}' contains invalid control characters.")

    allowed = PRESENTATION_ATTRIBUTES | GEOMETRY_ATTRIBUTES[tag]
    if name not in allowed:
        _fail(f"SVG attribute '{name}' is not allowed on <{tag}>.")

    if name in _NUMERIC_GEOMETRY_ATTRIBUTES:
        value = _number_text(_finite_number(value, name))
    elif name == "viewBox":
        x, y, width, height = _parse_view_box(value)
        value = " ".join(_number_text(number) for number in (x, y, width, height))
    else:
        value = " ".join(value.split()) if name == "points" else value
    return name, value


def _parse_points(value: str, label: str) -> list[float]:
    parts = [part for part in _SPLIT_NUMBERS_RE.split(str(value or "").strip()) if part]
    if not parts or len(parts) % 2:
        _fail(f"SVG {label} points must contain coordinate pairs.")
    return [_finite_number(part, f"{label} points") for part in parts]


def _shape_is_drawable(tag: str, attributes: dict[str, str]) -> bool:
    if tag == "path":
        path_data = str(attributes.get("d") or "").strip()
        return bool(path_data and _DRAW_COMMAND_RE.search(path_data))
    if tag == "rect":
        return (
            _finite_number(attributes.get("width", "0"), "rect width") > 0
            and _finite_number(attributes.get("height", "0"), "rect height") > 0
        )
    if tag == "circle":
        return _finite_number(attributes.get("r", "0"), "circle radius") > 0
    if tag == "ellipse":
        return (
            _finite_number(attributes.get("rx", "0"), "ellipse rx") > 0
            and _finite_number(attributes.get("ry", "0"), "ellipse ry") > 0
        )
    if tag in {"polygon", "polyline"}:
        points = _parse_points(attributes.get("points", ""), tag)
        minimum = 6 if tag == "polygon" else 4
        return len(points) >= minimum
    if tag == "line":
        x1 = _finite_number(attributes.get("x1", "0"), "line x1")
        y1 = _finite_number(attributes.get("y1", "0"), "line y1")
        x2 = _finite_number(attributes.get("x2", "0"), "line x2")
        y2 = _finite_number(attributes.get("y2", "0"), "line y2")
        return x1 != x2 or y1 != y2
    return False


def _sanitize_element(element: ET.Element, *, is_root: bool = False) -> ET.Element | None:
    namespace, tag = _qualified_name(element.tag)
    _validate_namespace(namespace)

    if tag in _REMOVABLE_TAGS:
        if is_root:
            _fail("Clean SVG root must be <svg>.")
        return None
    if tag not in ALLOWED_TAGS:
        _fail(f"SVG element <{tag}> is not allowed by the Clean SVG contract.")
    if is_root and tag != "svg":
        _fail("Clean SVG root must be <svg>.")
    if not is_root and tag == "svg":
        _fail("Nested <svg> elements are not allowed by the Clean SVG contract.")

    if element.text and element.text.strip():
        _fail(f"SVG text content inside <{tag}> is not allowed.")

    attributes: dict[str, str] = {}
    for raw_name, raw_value in element.attrib.items():
        name, value = _validate_attribute(tag, raw_name, raw_value)
        attributes[name] = value

    if tag == "svg":
        view_box, width_text, height_text, _width, _height = _normalized_root_geometry(element)
        attributes["viewBox"] = view_box
        attributes["width"] = width_text
        attributes["height"] = height_text

    clean = ET.Element(f"{{{SVG_NAMESPACE}}}{tag}")
    attribute_order = ["viewBox", "width", "height"] if tag == "svg" else []
    emitted = set()
    for name in attribute_order:
        if name in attributes:
            clean.set(name, attributes[name])
            emitted.add(name)
    for name in sorted(attributes):
        if name not in emitted:
            clean.set(name, attributes[name])

    for child in list(element):
        sanitized_child = _sanitize_element(child, is_root=False)
        if sanitized_child is not None:
            clean.append(sanitized_child)
        if child.tail and child.tail.strip():
            _fail(f"SVG text content after <{_qualified_name(child.tag)[1]}> is not allowed.")

    if tag == "g":
        return clean if len(clean) else None
    if tag not in {"svg", "g"} and not _shape_is_drawable(tag, attributes):
        return None
    return clean


def sanitize_svg(
    svg_text: str,
    *,
    max_bytes: int = 2_000_000,
    max_nodes: int = 5_000,
    max_paths: int = 4_000,
) -> SanitizedSvg:
    if not isinstance(svg_text, str) or not svg_text.strip():
        _fail("SVG source must be a non-empty UTF-8 document.")
    if max_bytes <= 0 or max_nodes <= 0 or max_paths <= 0:
        _fail("SVG complexity limits must be positive.")

    source_bytes = len(svg_text.encode("utf-8"))
    if source_bytes > max_bytes:
        _fail(f"SVG source size exceeds the {max_bytes}-byte Clean SVG limit.")
    if _FORBIDDEN_DECL_RE.search(svg_text):
        _fail("SVG DTD/entity declarations are forbidden.")
    if _XML_STYLESHEET_RE.search(svg_text):
        _fail("SVG XML stylesheets are forbidden.")

    _validate_document_namespaces(svg_text)
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise SvgSanitizationError(f"SVG XML is malformed: {exc}") from exc

    root_namespace, root_tag = _qualified_name(root.tag)
    _validate_namespace(root_namespace)
    if root_tag != "svg":
        _fail("Clean SVG root must be <svg>.")

    node_count = 0
    path_count = 0
    for element in root.iter():
        node_count += 1
        _namespace, local_name = _qualified_name(element.tag)
        if local_name == "path":
            path_count += 1
        if node_count > max_nodes:
            _fail(f"SVG node count exceeds the Clean SVG node limit of {max_nodes}.")
        if path_count > max_paths:
            _fail(f"SVG path count exceeds the Clean SVG path limit of {max_paths}.")

    _view_box, _width_text, _height_text, width, height = _normalized_root_geometry(root)
    clean_root = _sanitize_element(root, is_root=True)
    if clean_root is None:
        _fail("SVG contains no valid root element.")

    drawable_count = sum(
        1
        for element in clean_root.iter()
        if _qualified_name(element.tag)[1] in ALLOWED_TAGS - {"svg", "g"}
    )
    if drawable_count <= 0:
        _fail("SVG contains no drawable vector geometry after normalization.")

    ET.register_namespace("", SVG_NAMESPACE)
    xml = ET.tostring(clean_root, encoding="unicode", short_empty_elements=True)
    if len(xml.encode("utf-8")) > max_bytes:
        _fail(f"Sanitized SVG size exceeds the {max_bytes}-byte Clean SVG limit.")

    final_node_count = sum(1 for _ in clean_root.iter())
    final_path_count = sum(
        1 for element in clean_root.iter() if _qualified_name(element.tag)[1] == "path"
    )
    return SanitizedSvg(
        xml=xml,
        width=width,
        height=height,
        node_count=final_node_count,
        path_count=final_path_count,
    )
