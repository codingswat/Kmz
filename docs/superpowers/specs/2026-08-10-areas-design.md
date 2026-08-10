# Areas and area size

Date: 2026-08-10
Status: approved

## Problem

`kml_parser` finds `Polygon`, `LineString`, `Model` and `Track` geometry, counts
it, and throws it away. That is the "2 non-point feature(s) skipped" line in
every summary. Someone handed a KMZ of land parcels currently gets an empty
workbook and a count of what they lost.

Areas should be kept, each with its own table of corners and a computed size.

## Decisions

| Question | Decision |
|---|---|
| Which geometry | `Polygon` only. `LineString`, `Model` and `Track` stay skipped |
| Where areas live | One `Areas` sheet, a banner per area, corners as rows |
| Holes | Subtracted from the size; their corners listed and marked |
| Units | m², hectares and km², side by side |
| How area is measured | Project to UTM in a single zone, then measure flat |

Rejected, with reasons:

- **A sheet per area.** Closest reading of "its own table", but Excel caps
  sheet names at 31 characters and forbids `/ \ ? * [ ]`, so real names get
  mangled, and forty areas means forty tabs.
- **Ignoring holes.** Reports a plot with a courtyard as larger than it is. A
  wrong number that looks reasonable is the worst failure mode here.
- **km² alone**, as originally asked for. A building plot reads `0.000234`,
  which is easy to misread by a factor of ten.
- **Routes and tracks.** Deferred, not refused. The same machinery would give
  `LineString` a length; nobody has asked for it yet.

## Measuring the area

Each corner is projected into UTM — the same flat metre grid already produced
in the Easting/Northing columns — and the polygon's area is then computed from
those metres with the shoelace formula. Holes are measured the same way and
subtracted.

**Every corner is forced into one zone**, the zone containing the polygon's
centroid, rather than each corner choosing its own. Without this an area
straddling a zone boundary mixes two different grids and the result is
meaningless. With it, error stays under roughly 0.1% for anything up to tens of
kilometres across.

Rejected: treating the Earth as a sphere, which needs no dependency but is
*less* accurate than UTM for the normal case, because the Earth is an
ellipsoid. And exact geodesic measurement via `pyproj`, which is accurate to
millimetres but wraps a large C library — the same class of dependency whose
packaging failure this project has just finished fixing. Neither buys accuracy
anyone asked for.

### Accepted limitations

**This is flat map area, as if the shape were traced on a map.** It is not
surface area following the terrain. A sloping hillside's true surface is larger
than its footprint. Terrain-following area needs elevation data the KML does
not carry.

**Some areas cannot be measured** and must say so rather than guess:

- Beyond UTM's limits (north of 84°N or south of 80°S).
- Spanning more than 6° of longitude, where forcing one zone distorts too far.
- Fewer than three distinct corners, which encloses nothing.

Each returns no size plus a warning naming the area. A blank cell with an
explanation beats a confident wrong number.

## Architecture

A new module, `kmz_points/geometry.py`. Shapes are a different concern from
coordinates, and `convert.py` is already "one point in, one conversion out".
Everything about polygons — the single-zone projection, the shoelace formula,
subtracting holes — lives here as pure functions with no I/O.

It returns a result, not a bare number:

```python
@dataclass(frozen=True)
class Measurement:
    square_metres: float | None
    problem: str | None      # why it could not be measured
```

This matches the existing rule that nothing raises on bad input: one bad shape
must never abort a batch, so an unmeasurable area comes back as `None` and a
reason, exactly as an unreadable file does today.

**Corners reuse `Point`.** An `Area` holds `outer: list[Point]` and
`holes: list[list[Point]]`. Corner rows then render through the existing
`_row_for` with all 23 columns — decimal degrees, D/M/S, UTM, MGRS — with no
new column logic. An area's corners are points that happen to belong to a
shape.

```python
@dataclass(frozen=True)
class Area:
    name: str
    description: str
    outer: list[Point]
    holes: list[list[Point]]
    source_file: str
```

### Changed files

**`kmz_points/kml_parser.py`** — `parse_points` becomes `parse_document`,
returning a result carrying both `.points` and `.areas`. It will no longer only
parse points, and leaving the old name is the kind of small lie that costs
someone an hour. One caller to update.

`Polygon` is read via `outerBoundaryIs`/`innerBoundaryIs` → `LinearRing` →
`coordinates`, matched on local name like everything else in that module, so
namespaced and namespace-less documents take the same path. A polygon inside
`MultiGeometry` is found the same way, since the search is by descendant.

**`kmz_points/models.py`** — adds `Area`; `ParseResult` gains `areas`;
`BatchSummary` gains `areas_extracted`, reported by `as_text()`.

**`kmz_points/pipeline.py`** — `LoadedFile` gains `areas`; `_collect` returns
areas alongside points; both exports pass them to the writer.

**`kmz_points/excel.py`** — `write_workbook` gains an optional `areas`
argument and writes the `Areas` sheet. Sheet order becomes **Points, Areas,
Issues**; Issues stays last so opening the file lands on data.

## The Areas sheet

Same three header rows and same 23 columns as Points, so corners read
identically. Each area is a grey banner, then its outer corners, then a lighter
sub-banner per hole followed by that hole's corners:

```
███ Plot 12 — 4,520 m² · 0.452 ha · 0.004520 km² · 6 corners ███
    corner rows (outer boundary)
░░░ hole 1 — 3 corners ░░░
    corner rows (hole)
███ Field 3 — area not measured: spans more than 6° of longitude ███
    corner rows
```

Reusing the banner for holes rather than adding a "ring" column keeps the
Points sheet unchanged and adds no concept the reader has not already met on
the Points sheet.

### Deliberately not built

The size lives in the banner as text, so it cannot be sorted or summed. If
totalling areas becomes a real need, the answer is a summary sheet with one row
per area — not numbers wedged into a merged banner. Deferred until asked for.

## Error handling

Consistent with the existing contract that a batch always exports what it could
read:

| Condition | Behaviour |
|---|---|
| Polygon with no valid corners | Skipped, warning names it, batch continues |
| Fewer than three distinct corners | Area kept, size blank, warning |
| Beyond UTM's latitude limits | Area kept, size blank, warning |
| Spans more than 6° of longitude | Area kept, size blank, warning |
| Malformed coordinate in a corner | That corner skipped, warning, area kept |
| No areas in the batch | No `Areas` sheet at all, not an empty one |

## Visible behaviour changes

- The samples' `Polygon` stops being counted as skipped, so
  `features_skipped` for the bundled samples drops from 2 to 1 — the
  `LineString` route is still skipped. `SAMPLE_SKIPPED_TOTAL` in the tests and
  the frozen build's `--selftest` both encode the old number and must change.
- `BatchSummary.as_text()` gains an areas line, which appears in the desktop
  app's status bar, the CLI output, and the web service's summary page.

## Testing

- `geometry.py` against shapes with known answers: a one-degree square near the
  equator, a small rectangle whose area is known in m², a square with a square
  hole (outer minus hole), a self-touching shape, a two-corner degenerate, a
  polar polygon, and one spanning more than 6° of longitude.
- Winding order must not matter: the same shape clockwise and anticlockwise
  gives the same positive area.
- A closing corner repeated as the last point must not change the result — KML
  writes rings closed, and double-counting it is a classic shoelace bug.
- Parser: a polygon is extracted, its holes are extracted, a polygon inside
  `MultiGeometry` is found, and `LineString` is still counted as skipped.
- Excel: the `Areas` sheet exists only when there are areas, each area has one
  banner, each hole has a sub-banner, corner rows are not confused with data
  rows by `data_rows()`, and an unmeasurable area's banner says why.
- The existing suite must keep passing apart from the two encoded counts above.
