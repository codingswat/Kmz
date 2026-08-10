"""Extracting points from a KML document.

Namespace handling is deliberately blunt: elements are matched on their local
name, so KML 2.2, the legacy Google Earth namespaces, and namespace-less files
all take the same path. Matching on a fixed namespace URI is the usual reason a
parser silently returns zero points.
"""

from __future__ import annotations

from lxml import etree, html

from kmz_points.models import Area, ParseResult, Point

# Geometry types that are counted but not extracted. LinearRing is excluded on
# purpose -- it lives inside Polygon and would double-count every shape, and
# Polygon is no longer here because its areas are now extracted.
_NON_POINT_GEOMETRY = {"LineString", "Model", "Track"}


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


def _parse_coordinate_list(text: str | None) -> list[tuple[float, float, float | None]]:
    """Parse a whitespace-separated run of ``lon,lat[,alt]`` triples.

    A ring's coordinates are one long run of them, unlike a Point which holds
    a single tuple. Unusable entries are dropped rather than failing the ring:
    one bad corner should not lose the whole shape.
    """
    if not text or not text.strip():
        return []

    corners = []
    for entry in text.split():
        try:
            corners.append(_parse_coordinate_tuple(entry))
        except (ValueError, TypeError):
            continue
    return corners


def _ring_corners(boundary, name: str, source_file: str) -> list[Point]:
    """The Points of a LinearRing inside an outer/inner boundary element."""
    corners: list[Point] = []
    for ring in _find_descendants(boundary, "LinearRing"):
        coordinates = _find_child(ring, "coordinates")
        raw = coordinates.text if coordinates is not None else None
        for lon, lat, alt in _parse_coordinate_list(raw):
            corners.append(
                Point(
                    name=name,
                    description="",
                    lon=lon,
                    lat=lat,
                    alt=alt,
                    source_file=source_file,
                )
            )
    return corners


def _parse_polygon(polygon, name: str, description: str, source_file: str) -> Area | None:
    """One Polygon element as an Area, or None if it has no usable outline."""
    outer: list[Point] = []
    for boundary in _find_descendants(polygon, "outerBoundaryIs"):
        outer.extend(_ring_corners(boundary, name, source_file))

    if not outer:
        return None

    holes = []
    for boundary in _find_descendants(polygon, "innerBoundaryIs"):
        corners = _ring_corners(boundary, name, source_file)
        if corners:
            holes.append(corners)

    return Area(
        name=name,
        description=description,
        outer=outer,
        holes=holes,
        source_file=source_file,
    )


def _parse_xml(data: bytes, result: ParseResult):
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


def parse_document(data: bytes, source_file: str) -> ParseResult:
    """Extract every Placemark Point and Polygon in a KML document.

    Never raises: unreadable documents and malformed coordinates are reported
    as warnings so one bad file cannot abort a batch.
    """
    result = ParseResult()

    root = _parse_xml(data, result)
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

        for polygon in _find_descendants(placemark, "Polygon"):
            area = _parse_polygon(polygon, name, description, source_file)
            if area is None:
                label = name or "<unnamed>"
                result.warnings.append(
                    f"{source_file}: skipped area {label} (no usable outline)"
                )
                continue
            result.areas.append(area)

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
