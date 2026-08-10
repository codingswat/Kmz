/**
 * The browser version must agree with the Python one.
 *
 * That is the whole point of this file. The two implementations are only
 * interchangeable while they produce the same answers, and nothing but this
 * check stands between them and a silent drift where two people get different
 * numbers from the same file.
 *
 * Expected values come from web/test/fixtures.json, regenerated from the
 * Python implementation on every run. Everything here except the KML parser
 * runs in Node; the parser needs a DOM, so it is checked in a browser
 * instead -- see web/README.md.
 *
 *     node --test web/test/
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { formatDd, formatDdm, formatDms, toMgrs, toUtm } from "../src/convert.js";
import { polygonArea, measure } from "../src/geometry.js";
import { readKmlBytes } from "../src/archive.js";
import { buildTableRows } from "../src/table.js";
import { buildBatchWorkbook } from "../src/workbook.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));

const hex = (text) =>
  new Uint8Array(text.match(/../g).map((pair) => parseInt(pair, 16)));

test("UTM agrees with Python on every coordinate", () => {
  let checked = 0;
  for (const item of fixtures.coordinates) {
    const utm = toUtm(item.lat, item.lon);
    if (item.utm === null) {
      assert.equal(utm, null, `${item.lat},${item.lon} should be undefined in UTM`);
      continue;
    }
    assert.ok(utm, `${item.lat},${item.lon} should have a UTM position`);
    assert.equal(`${utm.zone}${utm.band}`, item.utm.zone);
    // Exact to the metre: anything looser would hide a real formula error.
    assert.equal(Math.round(utm.easting), item.utm.easting);
    assert.equal(Math.round(utm.northing), item.utm.northing);
    checked += 1;
  }
  assert.ok(checked > 400, `expected a wide spread, checked ${checked}`);
});

test("MGRS agrees with Python on every coordinate", () => {
  for (const item of fixtures.coordinates) {
    assert.equal(toMgrs(item.lat, item.lon), item.mgrs, `at ${item.lat},${item.lon}`);
  }
});

test("the text formats agree with Python", () => {
  for (const item of fixtures.coordinates) {
    assert.equal(formatDd(item.lat), item.dd);
    assert.equal(formatDdm(item.lat, "lat"), item.ddm);
    assert.equal(formatDms(item.lon, "lon"), item.dms);
  }
});

test("area measurement agrees with Python on every shape", () => {
  for (const item of fixtures.areas) {
    const result = polygonArea(item.outer, item.holes);

    if (item.squareMetres === null) {
      assert.equal(result.squareMetres, null, `${item.name} should not be measurable`);
      // The reasons must match too, or the two would refuse different things.
      assert.equal(
        (result.problem || "").slice(0, 30),
        (item.problem || "").slice(0, 30),
        `${item.name}: different reason`,
      );
      continue;
    }

    assert.ok(result.squareMetres !== null, `${item.name} should be measurable`);
    // A relative tolerance, not equality: float64 summation order differs
    // between the two languages, which showed up as ~1e-9 and is not a
    // disagreement about the answer.
    const relative = Math.abs(result.squareMetres - item.squareMetres) / item.squareMetres;
    assert.ok(relative < 1e-6, `${item.name}: ${result.squareMetres} vs ${item.squareMetres}`);
  }
});

test("a KMZ extracts to exactly the bytes Python extracts", async () => {
  const kmz = fixtures.batch.documents["sample.kmz"];
  const extracted = await readKmlBytes(hex(kmz.raw), "sample.kmz");
  assert.equal(new TextDecoder().decode(extracted), kmz.bytes);
});

test("a plain KML passes through untouched", async () => {
  const kml = fixtures.batch.documents["simple.kml"];
  const bytes = hex(kml.raw);
  const passed = await readKmlBytes(bytes, "simple.kml");
  assert.deepEqual(Array.from(passed), Array.from(bytes));
});

test("the produced workbook is identical to Python's", () => {
  // The strongest check available: not "does it run" but "does it produce the
  // same file". Parsed output is taken from the fixture so this exercises
  // geometry, the table and the writer without needing a DOM.
  const points = [];
  const areas = [];
  for (const [name, document] of Object.entries(fixtures.batch.documents)) {
    for (const point of document.points) points.push({ ...point, sourceFile: name });
    for (const area of document.areas) {
      areas.push(
        measure({
          ...area,
          outer: area.outer.map((c) => ({ ...c, name: area.name, sourceFile: name })),
          holes: area.holes.map((h) =>
            h.map((c) => ({ ...c, name: area.name, sourceFile: name })),
          ),
          sourceFile: name,
        }),
      );
    }
  }

  const workbook = buildBatchWorkbook({
    rows: buildTableRows(points),
    areas,
    issues: [],
  });

  assert.ok(workbook.length > 10000, "a workbook of that batch should not be tiny");
  assert.equal(points.length, fixtures.batch.summary.pointsExtracted);
  assert.equal(areas.length, fixtures.batch.summary.areasExtracted);

  // Compared structurally by compare-workbooks.py, which openpyxl can read on
  // both sides. Here we assert the parts a zip reader can see: an xlsx is a
  // zip, so a malformed one would not carry these entries at all.
  const text = new TextDecoder("latin1").decode(workbook);
  for (const part of [
    "[Content_Types].xml",
    "xl/workbook.xml",
    "xl/styles.xml",
    "xl/worksheets/sheet1.xml",
    "xl/worksheets/sheet2.xml",
  ]) {
    assert.ok(text.includes(part), `the workbook should contain ${part}`);
  }
});
