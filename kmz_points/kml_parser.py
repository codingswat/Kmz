"""Extracting points from a KML document.

Namespace handling is deliberately blunt: elements are matched on their local
name, so KML 2.2, the legacy Google Earth namespaces, and namespace-less files
all take the same path. Matching on a fixed namespace URI is the usual reason a
parser silently returns zero points.
"""

from __future__ import annotations

import re

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


_BREAKS_AND_TABS = re.compile(r"[\t\r\n]+")


def _escape_attribute(text: str) -> str:
    """Make one key or value safe to join with ``=`` and ``"; "``.

    Without this a value holding a semicolon reads as two pairs and a value
    holding an equals sign moves the boundary between key and value, so two
    different attribute sets could flatten to the same cell. The backslash is
    escaped first: doing it last would double the ones the other two rules had
    just added.

    A cell is one line, so tabs and newlines become a space rather than
    something a reader has to widen the row to see.
    """
    cleaned = _BREAKS_AND_TABS.sub(" ", text).strip(" ")
    return cleaned.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;")


def _element_text(element) -> str:
    """All the text inside an element, as a browser's textContent gives it.

    ``.text`` alone stops at the first child element, which the port has no
    equivalent of -- and the two have to agree on the same string.
    """
    return "".join(element.itertext())


def _extended_data(placemark) -> str:
    """A placemark's ExtendedData flattened into one cell's worth of text.

    Two forms are read, both keyed on the ``name`` ATTRIBUTE:

        <ExtendedData><Data name="k"><value>v</value></Data></ExtendedData>
        <ExtendedData><SchemaData><SimpleData name="k">v</SimpleData>…

    A <Data> may also carry a <displayName>. That is presentation and may
    repeat between two different fields, so it makes a poor key and is not
    used as one.

    Untyped namespaced children -- <ExtendedData><ns:foo>v</ns:foo></…> -- are
    deliberately not read. There is no agreed key for them, and reading them
    would put arbitrary vendor XML into a spreadsheet cell.
    """
    extended = _find_child(placemark, "ExtendedData")
    if extended is None:
        return ""

    pairs = []
    for element in extended.iter():  # document order, both forms interleaved
        local = _local_name(element)
        if local == "Data":
            value = _find_child(element, "value")
            text = _element_text(value) if value is not None else ""
        elif local == "SimpleData":
            text = _element_text(element)
        else:
            continue

        key = element.get("name")
        # Nothing to label the value with, so there is no pair to write.
        if key is None:
            continue
        pairs.append(f"{_escape_attribute(key)}={_escape_attribute(text)}")

    return "; ".join(pairs)


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


def _ring_corners(boundary, name: str, attributes: str, source_file: str) -> list[Point]:
    """The Points of a LinearRing inside an outer/inner boundary element.

    A corner carries the area's attributes: they describe the placemark the
    ring belongs to, and a corner row on the Areas sheet is that placemark.
    """
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
                    attributes=attributes,
                )
            )
    return corners


def _parse_polygon(
    polygon, name: str, description: str, attributes: str, source_file: str
) -> Area | None:
    """One Polygon element as an Area, or None if it has no usable outline."""
    outer: list[Point] = []
    for boundary in _find_descendants(polygon, "outerBoundaryIs"):
        outer.extend(_ring_corners(boundary, name, attributes, source_file))

    if not outer:
        return None

    holes = []
    for boundary in _find_descendants(polygon, "innerBoundaryIs"):
        corners = _ring_corners(boundary, name, attributes, source_file)
        if corners:
            holes.append(corners)

    return Area(
        name=name,
        description=description,
        outer=outer,
        holes=holes,
        source_file=source_file,
        attributes=attributes,
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

        attributes = _extended_data(placemark)

        for geometry in placemark.iter():
            if _local_name(geometry) in _NON_POINT_GEOMETRY:
                result.skipped += 1

        for polygon in _find_descendants(placemark, "Polygon"):
            area = _parse_polygon(polygon, name, description, attributes, source_file)
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
                    attributes=attributes,
                )
            )

    return result
