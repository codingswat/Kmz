# Browser version

A second implementation of the same tool, running entirely in a browser. It
does **not** replace the desktop app or the LAN service — those are unchanged
and remain the primary product. This exists so the logic can be embedded in a
web platform, and because a conversion that runs in the browser never uploads
anything: no server, no password, no laptop that has to be awake.

## Why the risky parts were proven first

Two things had no obvious browser answer, so both were settled before any port
was written.

**Producing the workbook.** It needs merged header bands, per-column fills,
number formats, a frozen pane and more than one sheet. The widely used
community spreadsheet libraries either drop styling or bring a large
dependency back to get it. An xlsx is a zip of XML, so `src/zip.js` and
`src/xlsx.js` write both directly — no dependencies at all, and nothing about
the layout out of reach. Verified by generating a workbook in Node and opening
it with the Python side's own `openpyxl`: merges, fills, fonts, number
formats, column widths, the frozen pane and unicode all survive the trip.

**MGRS.** Python gets it from a compiled C library with no browser
equivalent, so `src/convert.js` implements UTM and MGRS directly. Checked
against the Python implementation over 410 coordinates — the equator, both
hemispheres, the Norway and Svalbard zone exceptions, the poles, the
antimeridian, and 400 random points:

```
zone+band mismatches : 0
max easting  Δ       : 0 m
max northing Δ       : 0 m
MGRS mismatches      : 0
format mismatches    : 0
```

## The cost to be aware of

The same logic now lives in two languages, and the day they disagree two
people get different numbers from the same file with no way to tell which is
right. The defence is that cross-check: one set of inputs with known-correct
answers that both implementations must satisfy. It is worth keeping, and
worth running whenever either side changes.

## Running it

**The simplest way: open `kmz-extractor.html`.** One self-contained file —
double-click it, email it, put it anywhere. No server, no install, no network.

Opening `index.html` directly does **not** work, and this is worth knowing
because it fails silently: browsers refuse ES module imports from a `file://`
origin, so the page renders and then does nothing at all. Use the single file,
or serve the folder:

```bash
cd web && python3 -m http.server 8777
```

`kmz-extractor.html` is built from `src/` and committed, so it must be rebuilt
whenever `src/` changes:

```bash
node web/build.mjs
```

CI fails if it is out of date.

To embed it in another platform, copy `src/` and call `convert(files)` from
`src/pipeline.js`; it takes `{name, bytes}` and returns
`{summary, workbook, filename}`.

## Tests

```bash
.venv/bin/python web/test/generate-fixtures.py   # expected values, from Python
node --test "web/test/*.test.mjs"
```

Run on every push by the **Browser version** CI job. The expected values are
regenerated from the Python implementation each time rather than committed, so
a drift between the two fails the build instead of being checked against a
stale reference.

### The one place a test is weaker than it looks

`src/kml.js` needs a DOM and Node has none, and this project has no
`package.json` and no `node_modules` on purpose. `test/kml.test.mjs` runs it
against `test/dom-shim.mjs`, a hand-written XML reader — and a much smaller
HTML one — sufficient for the three sample documents and nothing beyond them.

That is worth being precise about, because it is easy to over-read:

- It **does** check `kml.js` against Python: which elements it walks, how it
  matches a local name, what it counts as skipped, how it pairs a Polygon's
  outer ring with its holes, and how it reduces a CDATA description to plain
  text. That is the hand-maintained port logic, and it had no coverage at all
  before.
- It **does not** check that a browser's DOM behaves like the shim. It
  implements no HTML implied end tags, no namespace URIs, no DTDs, and no CSS
  selectors beyond bare tag names. Anything outside that it throws on rather
  than quietly returning something plausible.

So the browser run remains the authority for "`kml.js` works in a browser".
The shim answers the different question of whether `kml.js` agrees with
`kml_parser.py`, which nothing was asking before.

### Known coordinate gaps

Three places `src/convert.js` does not match Python. All three are boundaries
the 410-coordinate sweep misses, all three are pinned by name in
`test/cross-check.test.mjs`, and none is fixed yet:

| Input | Python | Browser |
|---|---|---|
| latitude exactly 84 | applies the Svalbard zone exception | does not (`< 84`, not `<= 84`) |
| longitude exactly 180 | folds to −180, zone 1 | zone 61, which does not exist |
| latitude outside −80…84 | an MGRS reference, via the polar UPS grid | nothing; UTM only |

The first two are one-line fixes; the third needs UPS implementing. The
projected metres are right in all three cases — it is the printed zone, and
the polar grid reference, that differ.

## Does it agree with the Python?

Yes, checked at every level rather than assumed:

| Check | Result |
|---|---|
| UTM and MGRS, 410 coordinates | 0 mismatches, exact to the metre |
| Area measurement, 136 shapes | 0 mismatches (worst 0.0007 m², float noise) |
| Refusal wording, all 6 reasons | identical, and each one reached by a shape |
| The 23 columns | header, kind, number format and band all identical |
| Table rows, 64 points | every cell identical |
| Area banner text, 136 + 23 areas | identical, including the numbers |
| KMZ extraction | byte-identical to Python's `zipfile` |
| KML parsing, real samples | points, areas, descriptions and skipped counts all match |
| **The finished workbook** | **410 cells, 0 mismatches** — value, type and number format, plus sheets, merges, widths and freeze panes |

The last row is the one that matters: the same three sample files through both
implementations produce workbooks a reader could not tell apart. Not the same
bytes — openpyxl and a hand-written writer order a zip and encode a style
differently, and always will — so both sides are reduced to what someone
opening the file would find and compared cell by cell. Fonts, fills and
alignment are deliberately outside that; see `kmz_points/workbook_facts.py`.

## Layout

| Path | Purpose |
|---|---|
| `index.html` | The page: drop zone, convert, download |
| `src/pipeline.js` | Orchestration — the entry point to embed |
| `src/kml.js` | Point and polygon extraction (needs a DOM) |
| `src/archive.js` | KMZ → KML bytes |
| `src/unzip.js` | ZIP reader, with the decompression-bomb cap |
| `src/geometry.js` | Area measurement |
| `src/convert.js` | Coordinate conversions, including UTM and MGRS |
| `src/table.js` | The 23 columns and five bands |
| `src/workbook.js` | The banded layout, banners and sheets |
| `src/xlsx.js` | Workbook writer: styles, merges, sheets |
| `src/zip.js` | Minimal ZIP writer |
| `test/dom-shim.mjs` | Just enough DOM to run `kml.js` in Node — read its header |
| `spike/` | The cross-checks, kept as runnable evidence |

Everything except `kml.js` runs unchanged in Node, which is what lets the
cross-checking happen offline. `kml.js` needs a DOM, so it runs against the
shim above for its agreement with Python and in a real browser for everything
else.
