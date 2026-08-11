# Eight improvements from the code review

Date: 2026-08-11
Status: proposed

## Problem

A review of the repository raised fourteen possible improvements. Eight were
chosen:

| # | Improvement |
|---|---|
| 2 | Read `<ExtendedData>`, which is currently invisible |
| 3 | Report each area's perimeter |
| 4 | Stop the desktop window freezing during load and export |
| 5 | Measure area on the ellipsoid instead of on a forced UTM zone |
| 6 | Refuse to measure a self-intersecting outline |
| 7 | Throttle repeated wrong passwords on the LAN service |
| 8 | Serve with a production WSGI server |
| 9 | Packaging, a lockfile, lint and type checking, and stray files |

Designing them surfaced a ninth piece of work that is not optional: **the
parity net does not cover what items 2, 3, 5 and 6 change.**

## The parity gap, discovered while designing

CI regenerates fixtures from Python and asserts the browser version agrees.
That check is narrower than it looks, and one part of it is not a check at all.

The test named `the produced workbook is identical to Python's` does not
compare workbooks. `generate-fixtures.py` serialises the Python workbook as hex
and **nothing reads it**. Its own comment defers the comparison to
`compare-workbooks.py`, a file that does not exist anywhere in the repository.
What the test actually asserts is that the file is over 10 KB, that the point
and area counts match, and that five zip entry names are present.

Verified directly, not inferred:

```
grep -rn "batch.workbook" web/test/ web/spike/   -> no matches
find . -name "compare-workbooks*"                -> no such file
```

Three further surfaces are unchecked:

- **The two `COLUMNS` lists are never compared.** Both row builders emit
  positional arrays. A column added on one side and not the other produces two
  different workbooks in silence.
- **Area banner text is never compared.**
- **Refusal strings compare only their first 30 characters**, which already
  hides a real divergence: Python emits `could not be projected ({exc})`, the
  browser emits a bare `could not be projected`.

`web/README.md` claims the workbook is identical "sheets, sizes, merges, freeze
panes, every cell". Nothing verifies that claim.

Item 2 adds a column. Items 3, 5 and 6 change the area number, the banner and
the refusal set. Each lands on a surface with no check under it. **The parity
net is therefore repaired first, and the features land on top of it.**

## Decisions

| Question | Decision |
|---|---|
| Area engine | Authalic sphere for area, Vincenty inverse for perimeter, the same formulas hand-written in both languages |
| Ellipsoid dependency | None. `geographiclib` is not adopted |
| Self-intersecting outline | Refused, with a reason |
| A hole that cannot be measured | Refuses the whole shape |
| Replacement for the UTM guards | A bounding-box extent ceiling, phrased about the shape |
| `ExtendedData` destination | One new `Attributes` column, 24th, in the details band |
| Order of work | The parity net first; nothing behavioural until it is real |

### Why authalic and not `geographiclib`

The review recommended `geographiclib`, and that recommendation was wrong. It
was reversed on measurement.

The cost of exactness is asymmetric here. Python could import `geographiclib`
cheaply, but CI requires the browser version to agree to a relative 1e-6, so
the browser would need roughly 780 lines of ported third-party numerical code
vendored into `web/src`, plus 30 KB on a committed single-file artifact and an
attribution obligation in a repository with no LICENSE file.

Running the *same* authalic formula in both languages makes parity exact by
construction rather than something to be achieved and policed — the same
reasoning that makes an integer comparison trustworthy without a tolerance.

Measured against `geographiclib` as ground truth:

| Shape | Authalic error | Today's UTM shoelace |
|---|---|---|
| Parcel, 0.001° at 50°N | 1.4e-11 | 3.4e-04 |
| 0.01° at the equator | 1.5e-11 | 2.0e-03 |
| Field, 0.1° at 50°N | 1.4e-09 | 3.0e-04 |
| 6° at 20°N | 1.3e-06 | 9.3e-04 |
| 20° at 10°N | 2.5e-05 | refused |
| Polar, 0.01° at 85°N | 1.8e-11 | refused |

Across all 127 measurable shapes in the CI fixtures the worst authalic error is
**3.3e-10**, against **2.0e-3** for the shoelace it replaces — closer to exact
by a factor of about six million, on the shapes this tool actually measures.
Authalic error only becomes visible on continent-sized polygons, which this
tool does not measure, and even there it is 0.0025%.

Perimeter comes from a Vincenty inverse per edge, which agrees with
`geographiclib` to 1.75e-9 across every fixture ring — a micron per kilometre.

That is roughly 110 hand-written, reviewable lines per language against 780
vendored ones plus a dependency, and it buys back decimal places that sit well
below the precision of a KML coordinate.

### Rejected, with reasons

- **`geographiclib` plus a vendored JS port.** Exact to millimetres, at the
  cost of a dependency, 780 lines of third-party numerics, bundle growth, a
  lockfile pin that fixes every reference number in the cross-check, and parity
  that must be verified rather than free. The 2026-08-10 areas spec rejected
  `pyproj` on this same axis. The remaining accuracy is below the noise floor
  of the input.
- **Keeping the UTM shoelace and adding only perimeter and the crossing check.**
  Cheapest, but leaves a 0.2% error and the polar and 6°-span refusals in place
  when the alternative removes all three for about 110 lines.
- **A sweep-line self-intersection test.** Designed with an event queue and a
  two-million-comparison budget. Real rings are tens to low hundreds of corners,
  where naive all-pairs is microseconds, and the budget constant would have been
  the one parity surface with no cross-check under it. Reduced to naive
  all-pairs over non-adjacent edges with a corner ceiling, which is about 25
  lines per side and is itself cross-checkable.
- **`linkedom` for a DOM in the JS parser tests.** Would introduce npm, a
  lockfile and `node_modules` to a repository that deliberately has none, for a
  DOM that is neither Chrome's nor lxml's.
- **Per-key `ExtendedData` columns.** Most useful in Excel, but the column count
  would vary per batch and it breaks the rule that `COLUMNS` is the single
  definition of the table.
- **Merging `ExtendedData` into `Description`.** No schema change, but it blurs
  what a person wrote with what an exporter attached.

## The area engine

`kmz_points/geometry.py` and `web/src/geometry.js` keep their shape — pure
functions, nothing raises, an unmeasurable shape returns a `Measurement`
carrying the reason. What changes is how the number is produced.

**Area.** Each corner's geodetic latitude is converted to authalic latitude,
which is the latitude on a sphere of equal area, then the spherical excess is
summed by the tangent form:

```
2 * atan2( tan(Δλ/2) * (tan(β₁/2) + tan(β₂/2)),  1 + tan(β₁/2) * tan(β₂/2) )
```

The tangent form is used rather than the naive spherical-excess formula because
it keeps its significant digits on small polygons, which is the normal case.
Δλ is normalised into (-π, π], so a ring crossing the antimeridian works
without special handling.

Holes are measured the same way and subtracted by magnitude. As today, the sign
tracks winding direction and callers take the absolute value, so a shape's size
does not depend on which way round it was drawn. Verified: reversing a ring
negates the result bit-for-bit, and hole winding is therefore irrelevant.

**Perimeter.** A Vincenty inverse per edge, summed. `Measurement` gains
`perimeter_metres` / `perimeterMetres`.

**Refusals.** Two of today's four disappear, because the reason for them was
the projection. Two remain and two are added:

| Refusal | Status |
|---|---|
| Fewer than three distinct corners | Kept |
| A corner off the world, or not finite | Kept in effect, now an explicit guard. It currently surfaces only as a caught projection exception, which is why its message carries interpolated text the browser version does not reproduce |
| Beyond 84°N / 80°S | **Removed** — polar shapes now measure |
| Spans more than 6° of longitude | **Removed** — replaced by the extent ceiling |
| Outline crosses itself | **New** |
| Larger than the extent ceiling | **New** |
| A hole that cannot be measured | **New** — was a silent skip |

All refusal strings become fixed literals with no interpolated exception text,
so the two languages agree by construction and the 30-character truncation in
the cross-check can be dropped for strict equality.

### The extent ceiling

Dropping the projection drops the only thing that currently catches a mis-keyed
coordinate. A single wrong digit can turn a parcel into a continent, and the
new maths would measure it without complaint.

A ring whose bounding box exceeds **10° in either direction** is refused with
`is larger than any plot this tool is meant to measure`.

**This is the one number in this design chosen by judgement rather than
measurement, and it is flagged as such.** Every measurable shape in the CI
fixtures is under 0.05°, so 10° leaves about two hundred times headroom over
anything real, while still catching a coordinate displaced to another continent.
It is a named constant with this reasoning beside it, and it should be raised if
a real file ever hits it. It replaces a 6° limit that existed for a reason that
no longer applies, so it is deliberately not set to 6.

### Self-intersecting outlines

Naive all-pairs over non-adjacent edge pairs, in lat/lon degrees, using an
orientation predicate. Adjacent pairs share an endpoint by construction and are
excluded, including the wraparound pair joining the last edge to the first.

Above **512 corners** the check is skipped rather than run, and the shape is
measured. The ceiling is a named constant asserted on both sides and covered by
a fixture ring, so it cannot drift between the two implementations.

A shape whose outline crosses itself is refused with
`its outline crosses itself`. Both the shoelace and the ellipsoid formula return
the signed sum for such a ring, in which the lobes partly cancel, so the number
that would otherwise be reported is not the area of anything.

This is a behaviour change: a lollipop or a doubled-back spike is measured today
and will be refused. That is the intended direction — the areas spec's rule is
that a blank cell with an explanation beats a confident wrong number.

### Holes that cannot be measured

Today a hole that cannot be measured is skipped with a bare `continue`, and the
shape's area is reported too large with nothing on the sheet saying so. That is
precisely the failure the areas spec rejected when it refused to ignore holes:
"reports a plot with a courtyard as larger than it is. A wrong number that looks
reasonable is the worst failure mode here."

The whole shape is now refused, with a reason naming the hole.

### The banner

```
An area — 956,863 m² · 95.686 ha · 0.956863 km² · 3,996 m perimeter · 4 corners
```

Python's `format` rounds half-to-even; JavaScript's `toLocaleString` rounds
half-away-from-zero, and it rounds the shortest decimal representation of the
double rather than the double itself. These disagree at 3 and 6 decimal places,
not only at 0 — `format(95.6865, ',.3f')` is `95.686` where `toLocaleString`
gives `95.687`. A shared `groupedFixed` helper does the rounding explicitly on
both sides, and the banner cross-check pins the measured divergent cases.

## `ExtendedData`

Two forms are read, both matched on local name like everything else in the
parser, so namespaced and namespace-less documents take the same path:

```xml
<ExtendedData><Data name="k"><value>v</value></Data></ExtendedData>
<ExtendedData><SchemaData><SimpleData name="k">v</SimpleData></SchemaData></ExtendedData>
```

A `<Data>` element may also carry `<displayName>`; the `name` attribute is used,
not the display name, because the display name is presentation and may repeat.

Untyped namespaced children are not read. They have no agreed key semantics and
would put arbitrary vendor XML in a spreadsheet cell.

**Serialisation.** Keys and values are escaped before joining, so the result is
unambiguous rather than merely usually readable: `\` becomes `\\`, `=` becomes
`\=`, `;` becomes `\;`, and newlines and tabs collapse to a single space. Pairs
are joined with `; ` in document order. An empty or absent `ExtendedData` yields
`""`, never `None`.

**Model.** `Point` and `Area` gain `attributes: str = ""`, defaulted so existing
positional construction keeps working. The pre-formatted string is stored rather
than a dict, because `Point` is a frozen dataclass and the formatting rule must
be identical in both languages anyway.

**Column.** One new `Column("Attributes", "text", DETAILS, ...)` placed after
`Description`, and the matching entry in `web/src/table.js`, plus one new
element in each positional row builder. `tests/test_table.py` pins the full
column order in a fixture that deliberately does not import `COLUMNS`; that
fixture is updated by hand, which is the point of it.

**Area corners.** Corner rows carry the area's attributes. They currently
hard-code `description=""`, which is why the Description column on the Areas
sheet is always blank; the new column does not repeat that.

## The desktop window

`load_file` and `export_to_excel` move off the Tk main thread. Tk is not
thread-safe, so results return through a `queue.Queue` drained by a
`root.after` poll on the main thread — the worker never touches a widget.

While work is running the status line says what is happening, and Browse,
Export and Remove are disabled. There is no progress bar: per-file progress is
honest only for load, and a fake bar for export would be worse than a clear
message.

Re-entrancy is guarded by a single busy flag. Files dropped while a load is
running are queued and picked up when it finishes. The window closing mid-work
does not block: workers are daemon threads and check a cancelled flag between
files.

Cancellation is not offered. A batch is seconds to tens of seconds, and a
Cancel button that cannot interrupt a single large file's parse would lie.

**Testability** is the hard part, because the existing tests call `add_paths`
and then assert on `self.loaded` immediately. `App` takes an injected executor
defaulting to a real thread pool; tests inject a synchronous one that runs the
work inline, so every existing assertion holds unchanged. A separate test
covers the threaded path explicitly.

## The LAN service

**Throttling.** In-memory, per-IP, guarded by a `threading.Lock` because
`serve.py` runs threaded. After five failures within sixty seconds an IP gets
`429` until the window expires; a successful login clears its entry. The table
is bounded and evicts expired entries on write, so it cannot grow without limit.

No blocking sleep. A delay would tie up a worker thread, which is a denial of
service against the colleagues the throttle is supposed to protect.

This is honest about its threat model: one shared password on a trusted office
LAN over plain HTTP. Throttling makes a brute-force noisy and slow. It does not
make the service safe to expose to the internet, and `BUILDING.md` continues to
say so.

Existing tests post wrong passwords repeatedly. The throttle is therefore
constructed per-app with the limit configurable, and the test client's fixtures
get a fresh app, so the suite cannot become order-dependent.

**WSGI server.** `waitress`, not `gunicorn`, which does not run on Windows.
`serve.py` keeps its `_run_app` seam so tests can still start everything except
the server. `waitress` goes in the `web` extra, and `build.spec` excludes it
alongside Flask — the desktop app never serves.

`MAX_CONTENT_LENGTH` and the 413 page are re-verified under `waitress`
specifically, because it and the Werkzeug development server differ in how they
treat a client that keeps sending after the limit is reached.

## Housekeeping

`pyproject.toml` carries metadata, `requires-python`, core dependencies and
extras `[gui]`, `[web]`, `[dev]`, plus console entry points. `requirements.txt`
is deleted and its eight live references updated, including `BUILDING.md`,
`README.md` and the workflow.

`waitress` must be in the `web` extra, or the CI build job's pytest and the new
lint job both break.

A `requirements-release.txt` lockfile pins the release build only; developers
keep flexible floors. Ruff and mypy are configured to pass on today's code, with
rule selections chosen so adoption does not produce a large diff, and run in a
`lint` job that gates the release alongside `build` and `web`.

`.DS_Store` is gitignored. The stray `.claude/settings.local 2.json` is deleted
by the owner, not by this work.

`README.md` says 301 tests; there are 331.

## Order of work

Two rules: nothing behavioural lands before the workbook comparison is real, and
the table and banner cross-checks land before the column and the banner change.

1. Gitignore, stray files, the test count in `README.md`.
2. Ruff and mypy config, their fixes, a `lint` job that does not yet gate.
3. `pyproject.toml`, delete `requirements.txt`, update every reference.
4. `requirements-release.txt`; the release gates on `lint` too.
5. `bundle.test.mjs` stops rewriting `kmz-extractor.html` as a side effect.
6. **The workbook fact set.** A normalised description of a workbook — sheet
   names and order, every cell's value and type, number formats, merged ranges,
   freeze panes, column widths — emitted by both sides and compared. Deletes the
   fake "identical workbook" test.
7. Table cross-check: the two `COLUMNS` lists and a row-level comparison.
8. Banner cross-check, including `groupedFixed` and the rounding cases.
9. Refusal-string parity: drop the 30-character truncation, fix the divergence
   it hides.
10. A parser cross-check for `web/src/kml.js`, which today has none.
11. `ExtendedData` in Python only — model, parser, samples, tests. Green with no
    JS change, because the column does not exist yet.
12. The 24th column, both row builders, the JS mirror, bundle rebuild.
13. **The area engine, atomically across both languages.** Authalic area,
    Vincenty perimeter, the new refusal set, the extent ceiling, the
    self-intersection check, the hole rule, the banner. This cannot be staged:
    the cross-check compares the two implementations, so they change together or
    CI is red.
14. The desktop window.
15. Throttling and `waitress`.

Items 14 and 15 have no parity surface and can move earlier if convenient.

## Testing

Every existing test keeps passing except where this document says otherwise.
Baseline is 331 Python tests and 12 node tests, both green.

- `tests/test_geometry.py` validates against an independent cos-latitude
  estimate at 1% rather than against numbers this code produced. Measured: the
  new engine's worst error against that estimate is 0.67%, so it still passes.
  The tolerance is deliberately **not** widened.
- New geometry tests: a bowtie, a lollipop, a valid concave ring, collinear
  corners, a ring at the corner ceiling, a shape at and just over the extent
  ceiling, a polar shape, an antimeridian-crossing shape, a broken hole.
- New parity tests as described in steps 6 to 10.
- GUI tests keep their current assertions via the synchronous executor, plus one
  test that exercises the threaded path.
- Throttle tests cover the limit, the window, the reset on success and eviction.

## Risks

- **Every area number in every workbook changes**, by up to 0.2%. The direction
  is toward truth. It needs a line in the README and in the release notes; a
  reader comparing a new workbook to an old one must not think it is a bug.
- **Shapes measured today start being refused**: self-intersecting outlines, and
  anything over the extent ceiling. Deliberate, but visible.
- **Shapes refused today start being measured**: polar shapes, and anything
  between 6° and 10°.
- Step 13 is a large atomic change across two languages. It is last for that
  reason, on top of a parity net that will actually catch a divergence.
- The extent ceiling is a judgement call, not a measurement.
