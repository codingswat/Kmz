"""Extracting points from a KML document.

Namespace handling is deliberately blunt: elements are matched on their local
name, so KML 2.2, the legacy Google Earth namespaces, and namespace-less files
all take the same path. Matching on a fixed namespace URI is the usual reason a
parser silently returns zero points.
"""

from __future__ import annotations

from lxml import etree, html

from kmz_points.models import ParseResult, Point

# Geometry types that are counted but not extracted. LinearRing is excluded
# on purpose -- it lives inside Polygon and would double-count every shape.
_NON_POINT_GEOMETRY = {"LineString", "Polygon", "Model", "Track"}


def _local_name(element) -> str | None:
    tag = element.tag
    if not isinstance(tag, str):  # comments and processing instructions
        return None
    return tag.rsplit("}", 1)[-1]


def _find_descendants(element, name: str) -> list:
    return [e for e in element.iter() if _local_name(e) == name]


def _find_child(element, name: str):
    for child in element:
        if _local_name(child) == name:
            return child
    return None


def _plain_text(raw: str | None) -> str:
    """Reduce CDATA/HTML description markup to a single line of plain text."""
    if not raw or not raw.strip():
        return ""
    if "<" not in raw:
        return " ".join(raw.split())
    try:
        fragment = html.fromstring(f"<div>{raw}</div>")
    except Exception:
        return " ".join(raw.split())
    # Give breaks and block elements a separator, or words either side of them
    # run together once the tags are removed.
    for element in fragment.iter():
        if _local_name(element) in ("br", "p", "div", "li", "tr"):
            element.tail = "\n" + (element.tail or "")
    return " ".join(fragment.text_content().split())


def _parse_coordinate_tuple(text: str | None) -> tuple[float, float, float | None]:
    """Parse a KML ``lon,lat[,alt]`` triple. Raises ValueError if unusable."""
    if not text or not text.strip():
        raise ValueError("empty coordinates")
    # A Point holds a single tuple; take the first if an exporter wrote more.
    first = text.split()[0]
    parts = first.split(",")
    if len(parts) < 2:
        raise ValueError(f"expected lon,lat but got {first!r}")
    lon = float(parts[0])
    lat = float(parts[1])
    alt = float(parts[2]) if len(parts) > 2 and parts[2].strip() else None
    return lon, lat, alt


def _parse_document(data: bytes, result: ParseResult):
    """Return a root element, recovering from minor damage where possible."""
    strict = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        return etree.fromstring(data, parser=strict)
    except etree.XMLSyntaxError:
        pass

    lenient = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(data, parser=lenient)
    except etree.XMLSyntaxError:
        root = None

    if root is None:
        result.warnings.append("file is not valid XML and could not be read")
        return None

    result.warnings.append("file contains malformed XML; recovered what was readable")
    return root


def parse_points(data: bytes, source_file: str) -> ParseResult:
    """Extract every Placemark Point in a KML document.

    Never raises: unreadable documents and malformed coordinates are reported
    as warnings so one bad file cannot abort a batch.
    """
    result = ParseResult()

    root = _parse_document(data, result)
    if root is None:
        return result

    for placemark in _find_descendants(root, "Placemark"):
        name_element = _find_child(placemark, "name")
        name = (name_element.text or "").strip() if name_element is not None else ""

        description_element = _find_child(placemark, "description")
        description = _plain_text(
            description_element.text if description_element is not None else None
        )

        for geometry in placemark.iter():
            if _local_name(geometry) in _NON_POINT_GEOMETRY:
                result.skipped += 1

        for point_element in _find_descendants(placemark, "Point"):
            coordinates = _find_child(point_element, "coordinates")
            raw = coordinates.text if coordinates is not None else None
            try:
                lon, lat, alt = _parse_coordinate_tuple(raw)
            except (ValueError, TypeError) as exc:
                label = name or "<unnamed>"
                result.warnings.append(f"{source_file}: skipped {label} ({exc})")
                continue

            result.points.append(
                Point(
                    name=name,
                    description=description,
                    lon=lon,
                    lat=lat,
                    alt=alt,
                    source_file=source_file,
                )
            )

    return result
