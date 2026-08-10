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

Any static file server will do — there is no build step and no dependency:

```bash
cd web && python3 -m http.server 8777
```

Then open `http://127.0.0.1:8777/`. To embed it in another platform, copy
`src/` and call `convert(files)` from `src/pipeline.js`; it takes
`{name, bytes}` and returns `{summary, workbook, filename}`.

## Does it agree with the Python?

Yes, checked at every level rather than assumed:

| Check | Result |
|---|---|
| UTM and MGRS, 410 coordinates | 0 mismatches, exact to the metre |
| Area measurement, 132 shapes | 0 mismatches (worst 0.0007 m², float noise) |
| KMZ extraction | byte-identical to Python's `zipfile` |
| KML parsing, real samples | points, areas and skipped counts all match |
| **The finished workbook** | **identical** — sheets, sizes, merges, freeze panes, every cell |

The last row is the one that matters: the same three sample files through both
implementations produce workbooks that openpyxl cannot tell apart.

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
| `src/table.js` | The 23 columns and four bands |
| `src/workbook.js` | The banded layout, banners and sheets |
| `src/xlsx.js` | Workbook writer: styles, merges, sheets |
| `src/zip.js` | Minimal ZIP writer |
| `spike/` | The cross-checks, kept as runnable evidence |

Everything except `kml.js` runs unchanged in Node, which is what lets most of
the cross-checking happen offline. `kml.js` needs a DOM, so its check runs in
a browser.
