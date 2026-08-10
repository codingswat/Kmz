"""Parser tests.

The lon,lat ordering test is the one that matters most: KML stores
coordinates as lon,lat[,alt] while almost every UI presents lat,lon, so a
swap here is silent and produces plausible-looking wrong answers.
"""

import pytest

from kmz_points.kml_parser import parse_document

KML_22 = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Alpha</name>
      <description>First point</description>
      <Point><coordinates>38.123456,34.567890,120.5</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

KML_NO_NAMESPACE = """<?xml version="1.0" encoding="UTF-8"?>
<kml>
  <Document>
    <Placemark>
      <name>Bare</name>
      <Point><coordinates>10.5,20.25</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

KML_LEGACY_NAMESPACE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://earth.google.com/kml/2.1">
  <Document>
    <Placemark>
      <name>Legacy</name>
      <Point><coordinates>10.5,20.25</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

KML_NESTED = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Folder>
      <name>Outer</name>
      <Folder>
        <name>Inner</name>
        <Placemark>
          <name>Deep</name>
          <Point><coordinates>1.0,2.0</coordinates></Point>
        </Placemark>
      </Folder>
    </Folder>
  </Document>
</kml>"""

KML_MULTIGEOMETRY = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Cluster</name>
      <MultiGeometry>
        <Point><coordinates>1.0,2.0</coordinates></Point>
        <Point><coordinates>3.0,4.0</coordinates></Point>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>"""

KML_MIXED_GEOMETRY = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>A point</name>
      <Point><coordinates>1.0,2.0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>A line</name>
      <LineString><coordinates>1,2 3,4</coordinates></LineString>
    </Placemark>
    <Placemark>
      <name>A shape</name>
      <Polygon><outerBoundaryIs><LinearRing>
        <coordinates>1,2 3,4 5,6 1,2</coordinates>
      </LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
  </Document>
</kml>"""

KML_CDATA = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Styled</name>
      <description><![CDATA[<b>Bold</b> and <a href="http://x.test">a link</a><br/>Line two]]></description>
      <Point><coordinates>1.0,2.0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

KML_BAD_COORDS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Good</name>
      <Point><coordinates>1.0,2.0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Garbage</name>
      <Point><coordinates>not,a,number</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Empty</name>
      <Point><coordinates>   </coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Missing lat</name>
      <Point><coordinates>5.0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""


def parse(text, source="test.kml"):
    return parse_document(text.encode("utf-8"), source)


class TestCoordinateOrder:
    def test_kml_lon_lat_is_not_swapped(self):
        point = parse(KML_22).points[0]
        assert point.lon == 38.123456
        assert point.lat == 34.567890

    def test_altitude_is_read_when_present(self):
        assert parse(KML_22).points[0].alt == 120.5

    def test_altitude_is_none_when_absent(self):
        assert parse(KML_NO_NAMESPACE).points[0].alt is None


class TestNamespaces:
    def test_kml_22_namespace(self):
        assert len(parse(KML_22).points) == 1

    def test_no_namespace(self):
        result = parse(KML_NO_NAMESPACE)
        assert len(result.points) == 1
        assert result.points[0].name == "Bare"

    def test_legacy_google_earth_namespace(self):
        result = parse(KML_LEGACY_NAMESPACE)
        assert len(result.points) == 1
        assert result.points[0].name == "Legacy"


class TestNesting:
    def test_finds_placemarks_at_any_folder_depth(self):
        result = parse(KML_NESTED)
        assert len(result.points) == 1
        assert result.points[0].name == "Deep"

    def test_extracts_every_point_in_a_multigeometry(self):
        result = parse(KML_MULTIGEOMETRY)
        assert [(p.lon, p.lat) for p in result.points] == [(1.0, 2.0), (3.0, 4.0)]

    def test_multigeometry_points_inherit_the_placemark_name(self):
        assert {p.name for p in parse(KML_MULTIGEOMETRY).points} == {"Cluster"}


class TestNonPointGeometry:
    def test_a_polygon_does_not_become_a_point(self):
        result = parse(KML_MIXED_GEOMETRY)
        assert [p.name for p in result.points] == ["A point"]

    def test_only_the_line_is_counted_as_skipped_now(self):
        # The polygon used to be skipped alongside the line. It is extracted
        # as an area now, so only the LineString remains unhandled.
        assert parse(KML_MIXED_GEOMETRY).skipped == 1

    def test_the_polygon_is_kept_rather_than_discarded(self):
        assert len(parse(KML_MIXED_GEOMETRY).areas) == 1

    def test_a_linear_ring_is_never_counted_on_its_own(self):
        # LinearRing lives inside Polygon. Counting it as skipped geometry
        # would report the same shape twice.
        assert parse(KML_MIXED_GEOMETRY).skipped == 1


class TestDescriptions:
    def test_html_is_reduced_to_plain_text(self):
        description = parse(KML_CDATA).points[0].description
        assert "<b>" not in description
        assert "Bold" in description
        assert "a link" in description

    def test_line_breaks_become_whitespace_not_run_together_words(self):
        # text_content() alone yields "...a linkLine two"
        description = parse(KML_CDATA).points[0].description
        assert "linkLine" not in description
        assert "a link Line two" in description

    def test_plain_description_passes_through(self):
        assert parse(KML_22).points[0].description == "First point"

    def test_missing_description_is_empty_string(self):
        assert parse(KML_NO_NAMESPACE).points[0].description == ""


class TestFailSoft:
    def test_malformed_coordinates_do_not_lose_the_good_points(self):
        assert [p.name for p in parse(KML_BAD_COORDS).points] == ["Good"]

    def test_malformed_coordinates_are_reported_as_warnings(self):
        assert len(parse(KML_BAD_COORDS).warnings) == 3

    def test_corrupt_xml_returns_a_warning_instead_of_raising(self):
        result = parse("<kml><Document><unclosed>")
        assert result.points == []
        assert result.warnings

    def test_empty_document_yields_no_points_and_no_warnings(self):
        result = parse('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')
        assert result.points == []
        assert result.skipped == 0


class TestSourceAttribution:
    def test_each_point_records_its_source_file(self):
        result = parse(KML_22, source="places.kmz")
        assert result.points[0].source_file == "places.kmz"


class TestNames:
    def test_name_is_read(self):
        assert parse(KML_22).points[0].name == "Alpha"

    def test_missing_name_is_empty_string(self):
        kml = (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
            "<Point><coordinates>1,2</coordinates></Point></Placemark></Document></kml>"
        )
        assert parse(kml).points[0].name == ""

    def test_folder_name_is_not_mistaken_for_the_placemark_name(self):
        # <Folder><name>Outer</name> precedes the Placemark; a loose descendant
        # search would pick up "Outer" instead of "Deep"
        assert parse(KML_NESTED).points[0].name == "Deep"


POLYGON_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Plot 12</name>
      <description>A field</description>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          30.000,10.000,0 30.010,10.000 30.010,10.010 30.000,10.010 30.000,10.000
        </coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""

POLYGON_WITH_HOLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Courtyard plot</name>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>
          30.000,10.000 30.020,10.000 30.020,10.020 30.000,10.020
        </coordinates></LinearRing></outerBoundaryIs>
        <innerBoundaryIs><LinearRing><coordinates>
          30.005,10.005 30.010,10.005 30.010,10.010 30.005,10.010
        </coordinates></LinearRing></innerBoundaryIs>
        <innerBoundaryIs><LinearRing><coordinates>
          30.014,10.014 30.016,10.014 30.016,10.016
        </coordinates></LinearRing></innerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""

POLYGON_IN_MULTIGEOMETRY_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Wrapped</name>
      <MultiGeometry>
        <Polygon><outerBoundaryIs><LinearRing><coordinates>
          30.000,10.000 30.010,10.000 30.010,10.010
        </coordinates></LinearRing></outerBoundaryIs></Polygon>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>"""

ROUTE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>A route</name>
      <LineString><coordinates>1,2 3,4 5,6</coordinates></LineString>
    </Placemark>
  </Document>
</kml>"""


class TestAreas:
    def test_a_polygon_becomes_an_area(self):
        areas = parse(POLYGON_KML).areas
        assert len(areas) == 1
        assert areas[0].name == "Plot 12"
        assert areas[0].description == "A field"
        assert areas[0].source_file == "test.kml"

    def test_the_outer_ring_carries_its_corners_in_order(self):
        area = parse(POLYGON_KML).areas[0]
        # The ring is written closed, repeating the first coordinate last; the
        # parser keeps what the file said and lets the measurement decide.
        assert [(c.lon, c.lat) for c in area.outer][:3] == [
            (30.000, 10.000),
            (30.010, 10.000),
            (30.010, 10.010),
        ]

    def test_corner_altitude_is_kept_when_present(self):
        assert parse(POLYGON_KML).areas[0].outer[0].alt == 0

    def test_corners_are_attributed_to_their_source_file(self):
        area = parse(POLYGON_KML, source="plots.kmz").areas[0]
        assert {c.source_file for c in area.outer} == {"plots.kmz"}

    def test_every_hole_is_captured(self):
        area = parse(POLYGON_WITH_HOLE_KML).areas[0]
        assert len(area.holes) == 2
        assert len(area.holes[0]) == 4
        assert len(area.holes[1]) == 3

    def test_a_polygon_inside_multigeometry_is_found(self):
        assert len(parse(POLYGON_IN_MULTIGEOMETRY_KML).areas) == 1

    def test_a_polygon_is_no_longer_counted_as_skipped(self):
        # It used to be discarded and counted; now it is kept.
        assert parse(POLYGON_KML).skipped == 0

    def test_a_route_is_still_skipped(self):
        result = parse(ROUTE_KML)
        assert result.areas == []
        assert result.skipped == 1

    def test_a_document_with_no_polygons_has_no_areas(self):
        assert parse(KML_22).areas == []
