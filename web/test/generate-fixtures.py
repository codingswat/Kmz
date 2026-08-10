"""Write the expected values the browser version is checked against.

Everything here comes from the Python implementation, which is the reference.
The JavaScript is only correct insofar as it agrees with this.

    .venv/bin/python web/test/generate-fixtures.py

Writes web/test/fixtures.json, which the Node suite reads. Regenerate it
whenever the Python side changes -- CI does this on every run rather than
trusting a committed copy, so a drift between the two shows up as a failing
test rather than as a stale file nobody noticed.
"""

import json
import random
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kmz_points.convert import (  # noqa: E402
    format_dd,
    format_ddm,
    format_dms,
    to_mgrs,
    to_utm,
)
from kmz_points.geometry import polygon_area  # noqa: E402
from kmz_points.models import Point  # noqa: E402
from kmz_points.pipeline import export_to_excel, load_file  # noqa: E402
from kmz_points.samples import write_samples  # noqa: E402


def coordinate_cases():
    """A deterministic spread: the awkward places, then random cover."""
    random.seed(20260810)
    points = [
        (34.567890, 38.123456),
        (-0.180653, -78.467834),   # south, whole-degree part 0
        (-33.856784, 151.215297),
        (51.507351, -0.127758),
        (0.0, 0.0),
        (83.9, 20.0),              # near UTM's northern limit
        (-79.9, -170.0),           # near the southern limit, zone 2
        (56.5, 5.0),               # the Norway zone exception
        (72.5, 10.0),              # the Svalbard exceptions
        (60.0, 179.999),           # against the antimeridian
    ]
    points += [
        (random.uniform(-79.5, 83.5), random.uniform(-179.9, 179.9))
        for _ in range(400)
    ]

    cases = []
    for lat, lon in points:
        utm = to_utm(lat, lon)
        cases.append(
            {
                "lat": lat,
                "lon": lon,
                "utm": None
                if utm is None
                else {"zone": utm.zone, "easting": utm.easting, "northing": utm.northing},
                "mgrs": to_mgrs(lat, lon),
                "dd": format_dd(lat),
                "ddm": format_ddm(lat, "lat"),
                "dms": format_dms(lon, "lon"),
            }
        )
    return cases


def area_cases():
    random.seed(7)

    def corner(lat, lon):
        return Point("", "", lon, lat, None, "a.kml")

    def box(lat, lon, size):
        return [
            corner(lat, lon),
            corner(lat, lon + size),
            corner(lat + size, lon + size),
            corner(lat + size, lon),
        ]

    cases = []

    def add(name, outer, holes=()):
        result = polygon_area(outer, [list(h) for h in holes])
        cases.append(
            {
                "name": name,
                "outer": [{"lat": p.lat, "lon": p.lon} for p in outer],
                "holes": [[{"lat": p.lat, "lon": p.lon} for p in h] for h in holes],
                "squareMetres": result.square_metres,
                "problem": result.problem,
            }
        )

    add("equator box", box(0.0, 30.0, 0.01))
    add("northern box", box(50.0, 8.0, 0.01))
    add("southern box", box(-33.9, 151.2, 0.02))
    add("closed ring", box(10.0, 20.0, 0.01) + [corner(10.0, 20.0)])
    add("reversed winding", list(reversed(box(10.0, 20.0, 0.01))))
    add("one hole", box(10.0, 20.0, 0.02), [box(10.005, 20.005, 0.01)])
    add(
        "two holes",
        box(10.0, 20.0, 0.03),
        [box(10.002, 20.002, 0.005), box(10.015, 20.015, 0.005)],
    )
    add("hole swallows it", box(10.0, 20.0, 0.01), [box(10.0, 20.0, 0.05)])
    add("two corners", [corner(10.0, 20.0), corner(10.01, 20.0)])
    add("polar", box(85.0, 20.0, 0.01))
    add("spans many zones", [corner(10.0, 0.0), corner(10.0, 20.0), corner(10.1, 20.0), corner(10.1, 0.0)])
    add("empty", [])
    for index in range(120):
        add(
            f"random {index}",
            box(
                random.uniform(-70, 70),
                random.uniform(-179, 179),
                random.uniform(0.001, 0.05),
            ),
        )
    return cases


def sample_batch():
    """The real sample files, plus what Python's parser and writer make of them."""
    workspace = Path(tempfile.mkdtemp())
    order = {"simple.kml": 0, "nested.kml": 1, "sample.kmz": 2}
    paths = sorted(write_samples(workspace / "in"), key=lambda p: order[p.name])

    from kmz_points.archive import read_kml_bytes
    from kmz_points.kml_parser import parse_document

    documents = {}
    for path in paths:
        parsed = parse_document(read_kml_bytes(path), path.name)
        documents[path.name] = {
            "bytes": zipfile.ZipFile(path).read(
                next(n for n in zipfile.ZipFile(path).namelist() if n.endswith(".kml"))
            ).decode()
            if path.suffix == ".kmz"
            else path.read_bytes().decode(),
            "raw": path.read_bytes().hex(),
            "points": [
                {
                    "name": p.name,
                    "description": p.description,
                    "lon": p.lon,
                    "lat": p.lat,
                    "alt": p.alt,
                }
                for p in parsed.points
            ],
            "areas": [
                {
                    "name": a.name,
                    "description": a.description,
                    "outer": [{"lon": c.lon, "lat": c.lat, "alt": c.alt} for c in a.outer],
                    "holes": [
                        [{"lon": c.lon, "lat": c.lat, "alt": c.alt} for c in h]
                        for h in a.holes
                    ],
                }
                for a in parsed.areas
            ],
            "skipped": parsed.skipped,
        }

    out = workspace / "out"
    out.mkdir()
    summary = export_to_excel([load_file(p) for p in paths], out)

    return {
        "documents": documents,
        "workbook": Path(summary.output_path).read_bytes().hex(),
        "summary": {
            "filesRead": summary.files_read,
            "pointsExtracted": summary.points_extracted,
            "areasExtracted": summary.areas_extracted,
            "featuresSkipped": summary.features_skipped,
        },
    }


if __name__ == "__main__":
    target = Path(__file__).with_name("fixtures.json")
    target.write_text(
        json.dumps(
            {
                "coordinates": coordinate_cases(),
                "areas": area_cases(),
                "batch": sample_batch(),
            }
        )
    )
    print(f"wrote {target} ({target.stat().st_size // 1024} KB)")
