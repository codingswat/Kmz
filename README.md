# KML / KMZ Point Extractor

Desktop app that pulls every point out of KML and KMZ files, converts each one
into five coordinate formats, and writes the whole batch to a single Excel
table.

## Install

Python 3.10+ required.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On Linux, tkinter is a separate system package:

```bash
sudo apt install python3-tk      # Debian/Ubuntu
```

## Run

```bash
python run.py
```

Drag KML/KMZ files onto the drop zone, or use **Browse** to pick several at
once. Each file appears with its point count; select any and **Remove
selected** to drop them. The output folder defaults to the folder of the first
file you added. **Export to Excel** writes the workbook and reports what it
did.

There is also a headless CLI, which is what the end-to-end tests drive:

```bash
python -m kmz_points.cli file1.kml file2.kmz -o /path/to/output
python -m kmz_points.cli --make-samples samples/     # generate demo inputs
```

## Output

One workbook per batch, named `points_YYYYMMDD_HHMM.xlsx`, one row per point:

| No. | Name | Description | Lat (DD) | Lon (DD) | Lat (DDM) | Lon (DDM) | Lat (DMS) | Lon (DMS) | UTM Zone | Easting (m) | Northing (m) | MGRS | Altitude (m) | Source File |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

The header is bold and frozen, and column widths are fitted to content.
`Lat (DD)`, `Lon (DD)`, `Easting (m)`, `Northing (m)` and `Altitude (m)` are
stored as real numbers so they sort and work in formulas; the DDM, DMS, UTM
Zone and MGRS columns are formatted text.

### Coordinate formats

| Format | Example |
|---|---|
| Decimal degrees | `34.567890` |
| Degrees decimal minutes | `34° 34.0734' N` |
| Degrees minutes seconds | `34° 34' 4.40" N` |
| UTM | `37S 419595 E 3825474 N` |
| MGRS | `37SDU1959425474` |

In the UTM zone, the trailing letter is the **latitude band** (`37S` is band S,
not "south"). Rounding carries between units, so no output ever reads
`60.0000'` or `60.00"`.

UTM and MGRS are left blank for points where they are undefined — beyond
84°N or 80°S. Every other column is still filled for those rows.

## What gets extracted

Every `<Placemark>` containing a `<Point>`, at any folder depth, including
points inside a `<MultiGeometry>`. KML 2.2, the legacy Google Earth
namespaces, and namespace-less files all work.

`LineString` and `Polygon` features are not extracted, but they are counted and
reported as *"N non-point features skipped"*.

Descriptions are converted from CDATA/HTML to a single line of plain text.

### Failure handling

Nothing aborts a batch. A corrupt file, a KMZ with no KML inside, a file with
zero points, or a malformed coordinate produces a warning and is skipped; every
other file still exports.

## Tests

```bash
pytest
```

156 tests. The GUI tests need a display and skip without one; on a headless
machine run them under Xvfb:

```bash
xvfb-run -a pytest
```

## Layout

| Path | Purpose |
|---|---|
| `kmz_points/convert.py` | Coordinate formatting — pure functions |
| `kmz_points/archive.py` | KMZ → KML bytes |
| `kmz_points/kml_parser.py` | Placemark/Point extraction |
| `kmz_points/table.py` | `COLUMNS` + `build_table_rows()` |
| `kmz_points/excel.py` | Workbook writer |
| `kmz_points/pipeline.py` | Orchestration and batch summary |
| `kmz_points/cli.py` | Headless entry point |
| `kmz_points/gui.py` | tkinter shell |
| `kmz_points/samples.py` | Demo input generation |

The column layout is defined once, in `COLUMNS`. Adding or re-ordering a
column is a change to that list and nothing else.
