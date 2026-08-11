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
from kmz_points.excel import area_banner_text  # noqa: E402
from kmz_points.geometry import (  # noqa: E402
    REFUSALS,
    MeasuredArea,
    Measurement,
    polygon_area,
)
from kmz_points.models import Area, Point  # noqa: E402
from kmz_points.pipeline import export_to_excel, load_file  # noqa: E402
from kmz_points.samples import write_samples  # noqa: E402
from kmz_points.table import COLUMNS, build_table_rows  # noqa: E402
from kmz_points.workbook_facts import workbook_facts  # noqa: E402


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
    add(
        "spans many zones",
        [corner(10.0, 0.0), corner(10.0, 20.0), corner(10.1, 20.0), corner(10.1, 0.0)],
    )
    # 6.25 is an exact tie at one decimal place, so the refusal reads "6.2" in
    # Python and "6.3" from any rounder that breaks ties away from zero.
    add(
        "spans exactly 6.25 degrees",
        [corner(10.0, 0.0), corner(10.0, 6.25), corner(10.1, 6.25), corner(10.1, 0.0)],
    )
    # Wholly past the antimeridian, so the shape's centre is off the map too.
    # That is the one refusal that comes from projecting the centre, and it is
    # a different sentence from the one a bad corner produces.
    add(
        "centre past the antimeridian",
        [corner(10.0, 181.0), corner(10.0, 183.0), corner(10.1, 183.0), corner(10.1, 181.0)],
    )
    # Every check passes, the centre is on the map, and a corner is not.
    add(
        "corner past the antimeridian",
        [corner(10.0, 179.0), corner(10.0, 181.0), corner(10.1, 181.0), corner(10.1, 179.0)],
    )
    add(
        "hole past the antimeridian",
        box(10.0, 20.0, 0.05),
        [
            [
                corner(10.01, 179.0),
                corner(10.01, 181.0),
                corner(10.02, 181.0),
                corner(10.02, 179.0),
            ]
        ],
    )
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


def banner_text_for(case):
    """The exact banner Python writes for one of area_cases()' shapes."""
    def points(corners):
        return [Point("", "", c["lon"], c["lat"], None, "a.kml") for c in corners]

    area = Area(
        name=case["name"],
        description="",
        outer=points(case["outer"]),
        holes=[points(hole) for hole in case["holes"]],
        source_file="a.kml",
    )
    measurement = Measurement(case["squareMetres"], case["problem"])
    return area_banner_text(MeasuredArea(area, measurement))


def banner_number_cases():
    """Banners for sizes chosen to break a rounder, rather than found by luck.

    area_cases() measures real polygons, so the three numbers in each banner
    are whatever the shoelace sum happened to produce -- which is a poor way
    to reach the values where two languages round differently. Here the size
    is set directly, so the awkward ones can be asked for by name.

    One square_metres drives all three numbers: hectares is it over 1e4 and
    square kilometres over 1e6. Both divisors are exact powers of ten, so a
    size like 7812.5 stays exact all the way down and lands on a genuine tie
    at nought decimals (7,812.5 m2) and at six (0.0078125 km2).
    """
    corners = [
        {"lat": 10.0, "lon": 20.0},
        {"lat": 10.0, "lon": 20.01},
        {"lat": 10.01, "lon": 20.01},
        {"lat": 10.01, "lon": 20.0},
    ]

    sizes = [
        # Exact ties at nought places, where Python rounds to even and every
        # obvious JavaScript answer rounds away from zero.
        0.5, 1.5, 2.5, 3.5, 736.5, 547996.5,
        # m2 / 1e4 lands on an exact tie at three places: 625 -> 0.0625 ha.
        625.0, 1875.0, 3125.0, 7403125.0,
        # m2 / 1e6 lands on an exact tie at six places: 7812.5 -> 0.0078125.
        7812.5, 23437.5, 39062.5,
        # Not ties at all, but stored just below the decimal they print as --
        # the other half of the divergence, and the half toFixed also gets
        # right while toLocaleString does not.
        95.6865, 548.3335, 622704953.0995, 714109906.6749785,
        # Shape rather than rounding: grouping, and a size under a square metre.
        0.0, 1.0, 999.999, 1000.0, 1234567.891, 987654321.5,
    ]

    cases = []
    for size in sizes:
        area = Area(
            name=f"{size} m2",
            description="",
            outer=[Point("", "", c["lon"], c["lat"], None, "a.kml") for c in corners],
            holes=[],
            source_file="a.kml",
        )
        cases.append(
            {
                "name": area.name,
                "outer": corners,
                "squareMetres": size,
                "problem": None,
                "text": area_banner_text(MeasuredArea(area, Measurement(size))),
            }
        )
    return cases


def grouped_fixed_cases():
    """Values with Python's ``format(x, ',.Nf')``, for the JS helper alone.

    The banner only ever asks for nought, three and six places, so this is
    where the helper itself gets a wider workout: the ties above, a random
    spread, and the shapes that are easy to get wrong once rather than in a
    banner -- negative zero, subnormals, and a value large enough to make
    toFixed give up and return exponential notation.
    """
    random.seed(20260811)

    values = [
        0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1.5, 2.5, -2.5, 3.5,
        # Exact ties: m / 2**k, which is a tie at k decimal places for the
        # right k. 1/2 at nought, 1/16 at three, 1/128 at six.
        0.0625, 0.1875, 0.3125, 0.5625, 740.3125, 959.8125,
        0.0078125, 0.0234375, 0.0390625, 979902801.0078125,
        # Stored below the decimal they print as: a rounder that works from
        # the shortest representation rounds these the other way.
        95.6865, 548.3335, 462.3175, 81.4365, 802.4635, 378.6805,
        622704953.0995, 714109906.6749785, 296632730.2893085,
        # Sizes and shapes rather than ties.
        5e-324, 1e-300, 1e15 + 0.5, 1e20, 1e21, 123456789012345680.0,
        -1234567.891, 999.9995, 0.9999995,
    ]
    values += [random.uniform(0, 1e9) for _ in range(200)]
    values += [random.uniform(-1, 1) for _ in range(100)]
    values += [random.randrange(0, 10**7) + 0.5 for _ in range(100)]

    return [
        {"value": value, "places": places, "text": format(value, f",.{places}f")}
        for value in values
        for places in (0, 1, 3, 6)
    ]


def table_points(documents, coordinates):
    """The points the row builder is checked against, in row order.

    Three sources, each covering something the others cannot. The sample batch
    carries real names, descriptions, altitudes and source files. The
    coordinate cases carry the awkward geography -- the zone exceptions, the
    antimeridian, whole-degree parts of zero -- which seven sample points do
    not reach. The two polar points are the only way to exercise the columns
    that stay empty because UTM is undefined there.
    """
    points = [
        Point(p["name"], p["description"], p["lon"], p["lat"], p["alt"], name)
        for name, document in documents.items()
        for p in document["points"]
    ]
    points += [
        Point(area["name"], "", c["lon"], c["lat"], c["alt"], name)
        for name, document in documents.items()
        for area in document["areas"]
        for c in area["outer"]
    ]

    # The first ten coordinate cases are the deliberately awkward ones; the
    # rest are random cover, sampled rather than taken whole so the fixture
    # stays a readable size.
    spread = coordinates[:10] + coordinates[10::10]
    points += [
        Point(
            f"case {index}",
            "" if index % 3 else f"description {index}",
            case["lon"],
            case["lat"],
            None if index % 2 else index * 1.5,
            "spread.kml",
        )
        for index, case in enumerate(spread)
    ]

    points += [
        Point("north pole", "", 20.0, 85.0, 3.0, "polar.kml"),
        Point("south pole", "", 20.0, -85.0, None, "polar.kml"),
    ]
    return points


def table_facts(documents, coordinates):
    """The table's shape, and the rows Python builds from a spread of points.

    COLUMNS is hand-maintained in two languages and both row builders emit
    positional arrays, so a column added to one side and not the other changes
    what every cell after it means without any test noticing. These four lists
    are what web/test/table.test.mjs compares.
    """
    points = table_points(documents, coordinates)
    return {
        "headers": [column.header for column in COLUMNS],
        "kinds": [column.kind for column in COLUMNS],
        "numberFormats": [column.number_format for column in COLUMNS],
        "bands": [column.band.title for column in COLUMNS],
        "points": [
            {
                "name": p.name,
                "description": p.description,
                "lon": p.lon,
                "lat": p.lat,
                "alt": p.alt,
                "sourceFile": p.source_file,
            }
            for p in points
        ],
        "rows": build_table_rows(points),
    }


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
        # What the browser's workbook is actually checked against. The hex
        # above is the file itself, which no two writers produce identically;
        # these are the parts of it a reader would notice.
        "workbookFacts": workbook_facts(summary.output_path),
        "summary": {
            "filesRead": summary.files_read,
            "pointsExtracted": summary.points_extracted,
            "areasExtracted": summary.areas_extracted,
            "featuresSkipped": summary.features_skipped,
        },
    }


if __name__ == "__main__":
    target = Path(__file__).with_name("fixtures.json")
    coordinates = coordinate_cases()
    areas = area_cases()
    batch = sample_batch()

    target.write_text(
        json.dumps(
            {
                "coordinates": coordinates,
                "areas": areas,
                "batch": batch,
                "table": table_facts(batch["documents"], coordinates),
                # One banner per area case, in the same order, plus the ones
                # whose numbers were chosen rather than measured.
                "banners": [banner_text_for(case) for case in areas],
                "bannerNumbers": banner_number_cases(),
                "groupedFixed": grouped_fixed_cases(),
                "refusals": {
                    "templates": REFUSALS,
                    # Which of them the area cases actually reach. Without
                    # this the comparison could pass on two identical lists
                    # that neither implementation ever produces.
                    "exercised": sorted(
                        {case["problem"] for case in areas if case["problem"]}
                    ),
                },
            }
        )
    )
    print(f"wrote {target} ({target.stat().st_size // 1024} KB)")
