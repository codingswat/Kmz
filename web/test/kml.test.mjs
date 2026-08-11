/**
 * The KML parser must find what Python's finds.
 *
 * web/src/kml.js had no automated coverage at all: it is the only module that
 * needs a DOM, Node has none, and this repository has no package.json to add
 * one to. So the port of kmz_points/kml_parser.py -- which element names it
 * walks, what it counts as a skipped feature, how it pairs a Polygon's outer
 * ring with its holes -- was maintained by hand against nothing.
 *
 * It runs here against web/test/dom-shim.mjs. READ THAT FILE'S HEADER before
 * reading a pass from this one as more than it is: the shim is a hand-written
 * XML reader sufficient for these three documents, not a browser, so this
 * checks kml.js against Python and does NOT check kml.js against Chrome. The
 * browser check in web/README.md is still what covers that.
 *
 * Expected values come from web/test/fixtures.json, regenerated from the
 * Python implementation on every run.
 *
 *     node --test web/test/
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { installDom } from "./dom-shim.mjs";
import { parseDocument } from "../src/kml.js";

installDom();

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));
const documents = Object.entries(fixtures.batch.documents);

/** Python records a corner as lon/lat/alt; drop everything kml.js adds. */
const corner = (c) => ({ lon: c.lon, lat: c.lat, alt: c.alt });

test("the parser finds the same points Python finds", () => {
  for (const [name, expected] of documents) {
    const result = parseDocument(expected.bytes, name);
    assert.deepEqual(
      result.points.map((p) => ({
        name: p.name,
        description: p.description,
        lon: p.lon,
        lat: p.lat,
        alt: p.alt,
      })),
      expected.points,
      `${name}: different points`,
    );
    // sourceFile is the parser's own, and the row builder depends on it.
    assert.ok(
      result.points.every((point) => point.sourceFile === name),
      `${name}: a point came back attributed to another file`,
    );
  }
});

test("the parser finds the same areas Python finds", () => {
  for (const [name, expected] of documents) {
    const result = parseDocument(expected.bytes, name);
    assert.deepEqual(
      result.areas.map((area) => ({
        name: area.name,
        description: area.description,
        outer: area.outer.map(corner),
        holes: area.holes.map((hole) => hole.map(corner)),
      })),
      expected.areas,
      `${name}: different areas`,
    );
  }
});

test("the parser skips the same features Python skips", () => {
  for (const [name, expected] of documents) {
    assert.equal(parseDocument(expected.bytes, name).skipped, expected.skipped, name);
  }
});

test("the cross-check is looking at real documents", () => {
  // Every assertion above is satisfied by two empty lists. These are the
  // things the three sample files were written to contain, and the parser has
  // to actually be reaching them.
  const totals = documents.reduce(
    (running, [, document]) => ({
      points: running.points + document.points.length,
      areas: running.areas + document.areas.length,
      skipped: running.skipped + document.skipped,
      holes: running.holes + document.areas.reduce((n, area) => n + area.holes.length, 0),
    }),
    { points: 0, areas: 0, skipped: 0, holes: 0 },
  );
  assert.deepEqual(totals, { points: 7, areas: 1, skipped: 1, holes: 1 });

  const parsed = documents.flatMap(([name, document]) =>
    parseDocument(document.bytes, name).points,
  );

  // The awkward cases the samples exist to cover, each reached through the
  // parser rather than asserted about the fixture.
  assert.ok(
    parsed.some((point) => point.alt !== null) && parsed.some((point) => point.alt === null),
    "altitude is present on every point or on none",
  );
  assert.ok(
    parsed.some((point) => point.lat < 0) && parsed.some((point) => point.lon < 0),
    "no southern or western coordinate survived",
  );
  // A Point nested inside a MultiGeometry inside two Folders, which is the
  // shape a parser that only looks one level down misses.
  assert.ok(
    parsed.some((point) => point.name === "Echo cluster"),
    "the MultiGeometry point was not found",
  );
});

test("descriptions come back as the same plain text", () => {
  // The HTML path is separate from the XML one and is where the shim is
  // furthest from a browser, so it is worth naming: two of these came out of
  // CDATA carrying markup, and Python reduced them with lxml.
  const descriptions = documents.flatMap(([name, document]) =>
    parseDocument(document.bytes, name).points.map((point) => point.description),
  );
  const expected = documents.flatMap(([, document]) =>
    document.points.map((point) => point.description),
  );
  assert.deepEqual(descriptions, expected);

  // Specifically the two that had tags in them, so this cannot pass on seven
  // plain strings if the markup handling silently stopped running.
  assert.ok(
    expected.includes("Rich text with a link and a second line"),
    "the inline-markup description is not in the fixture any more",
  );
  assert.ok(
    expected.includes("Paragraph one Paragraph two"),
    "the block-markup description is not in the fixture any more",
  );
});

test("nothing raises on input that is not a document", () => {
  // The invariant the whole pipeline rests on: one bad file may not abort a
  // batch. Compared against nothing, because lxml's recovery and a browser's
  // are different by design -- what matters is the shape of the answer.
  const rubbish = [
    "",
    "   ",
    "not xml at all",
    "<kml><unclosed>",
    "</closed>",
    "<kml><Placemark><Point><coordinates>nonsense</coordinates></Point></Placemark></kml>",
    "<kml><Placemark><Point><coordinates></coordinates></Point></Placemark></kml>",
    "<kml><Placemark><Polygon><outerBoundaryIs><LinearRing>" +
      "<coordinates></coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>",
    "<kml><Placemark><name>x</name><Point><coordinates>1</coordinates></Point></Placemark></kml>",
  ];

  for (const text of rubbish) {
    const result = parseDocument(text, "bad.kml");
    assert.ok(Array.isArray(result.points), `${JSON.stringify(text)}: no points array`);
    assert.ok(Array.isArray(result.areas), `${JSON.stringify(text)}: no areas array`);
    assert.ok(Array.isArray(result.warnings), `${JSON.stringify(text)}: no warnings array`);
    assert.equal(typeof result.skipped, "number");
  }

  // And that the malformed ones are actually being rejected rather than
  // parsed into nothing by a shim that shrugs at anything.
  assert.ok(parseDocument("<kml><unclosed>", "bad.kml").warnings.length > 0);
  assert.ok(parseDocument("not xml at all", "bad.kml").warnings.length > 0);
});
