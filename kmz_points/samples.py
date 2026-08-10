"""Generated sample inputs.

Exercises the cases that break naive parsers: folder nesting, CDATA/HTML
descriptions, mixed geometry, MultiGeometry, altitudes, southern/western
coordinates, and a zipped KMZ.

Totals: 7 points, 2 non-point features.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

SIMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Simple</name>
    <Placemark>
      <name>Alpha</name>
      <description>A plain description</description>
      <Point><coordinates>38.123456,34.567890,120.5</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Bravo</name>
      <description>Second point</description>
      <Point><coordinates>-78.467834,-0.180653</coordinates></Point>
    </Placemark>
  </Document>
</kml>
"""

NESTED_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Nested</name>
    <Folder>
      <name>Outer folder</name>
      <Placemark>
        <name>Charlie</name>
        <description><![CDATA[<b>Rich</b> text with a <a href="http://example.test">link</a><br/>and a second line]]></description>
        <Point><coordinates>151.215297,-33.856784,58</coordinates></Point>
      </Placemark>
      <Folder>
        <name>Inner folder</name>
        <Placemark>
          <name>Delta</name>
          <description><![CDATA[<p>Paragraph one</p><p>Paragraph two</p>]]></description>
          <Point><coordinates>2.294481,48.858370</coordinates></Point>
        </Placemark>
        <Placemark>
          <name>Echo cluster</name>
          <description>Has a MultiGeometry</description>
          <MultiGeometry>
            <Point><coordinates>-0.127758,51.507351,11</coordinates></Point>
          </MultiGeometry>
        </Placemark>
      </Folder>
      <Placemark>
        <name>A route</name>
        <LineString>
          <coordinates>1,2 3,4 5,6</coordinates>
        </LineString>
      </Placemark>
      <Placemark>
        <name>An area</name>
        <description>A square kilometre with a courtyard cut out of it</description>
        <Polygon>
          <outerBoundaryIs><LinearRing>
            <coordinates>
              38.200000,34.600000 38.210900,34.600000
              38.210900,34.609000 38.200000,34.609000
              38.200000,34.600000
            </coordinates>
          </LinearRing></outerBoundaryIs>
          <innerBoundaryIs><LinearRing>
            <coordinates>
              38.203000,34.602000 38.205000,34.602000
              38.205000,34.604000 38.203000,34.604000
            </coordinates>
          </LinearRing></innerBoundaryIs>
        </Polygon>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""

KMZ_DOC_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Zipped</name>
    <Placemark>
      <name>Foxtrot</name>
      <description>Inside a KMZ</description>
      <Point><coordinates>139.691706,35.689487,40</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Golf</name>
      <description>Also inside the KMZ</description>
      <Point><coordinates>-122.419416,37.774929</coordinates></Point>
    </Placemark>
  </Document>
</kml>
"""


def write_samples(directory: str | Path) -> list[Path]:
    """Write the three sample inputs into ``directory`` and return their paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    simple = directory / "simple.kml"
    simple.write_text(SIMPLE_KML, encoding="utf-8")

    nested = directory / "nested.kml"
    nested.write_text(NESTED_KML, encoding="utf-8")

    kmz = directory / "sample.kmz"
    with zipfile.ZipFile(kmz, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", KMZ_DOC_KML)
        archive.writestr("files/pin.png", b"\x89PNG\r\n\x1a\n")  # a non-KML entry

    return [simple, nested, kmz]
