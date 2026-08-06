"""Parser tests.

The lon,lat ordering test is the one that matters most: KML stores
coordinates as lon,lat[,alt] while almost every UI presents lat,lon, so a
swap here is silent and produces plausible-looking wrong answers.
"""

import pytest

from kmz_points.kml_parser import parse_points

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
    return parse_points(text.encode("utf-8"), source)


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
    def test_line_and_polygon_are_not_extracted(self):
        result = parse(KML_MIXED_GEOMETRY)
        assert [p.name for p in result.points] == ["A point"]

    def test_line_and_polygon_are_counted_as_skipped(self):
        assert parse(KML_MIXED_GEOMETRY).skipped == 2

    def test_polygon_inner_linear_ring_is_not_double_counted(self):
        # Polygon contains a LinearRing; counting both would report 3
        assert parse(KML_MIXED_GEOMETRY).skipped == 2


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
