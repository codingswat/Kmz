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
import { polygonArea } from "../src/geometry.js";
import { readKmlBytes } from "../src/archive.js";

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
      // The whole reason, not its first thirty characters. Comparing a prefix
      // hid a live divergence for as long as it existed: Python interpolated
      // the caught exception's text and the browser did not, and every one of
      // those strings agrees for far longer than thirty characters.
      assert.equal(result.problem, item.problem, `${item.name}: different reason`);
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

/**
 * Three places the browser's coordinates are known NOT to match Python's.
 *
 * These are defects, not decisions, and none of them is fixed here: they live
 * in src/convert.js, they change numbers a workbook shows, and that is a
 * change to make deliberately with its own sweep behind it rather than as a
 * side effect of adding tests. They are written down instead, so that they
 * are a known quantity rather than a surprise, so that they cannot quietly
 * get worse, and so that whoever fixes one is told to delete the pin.
 *
 * The 410 coordinates above miss all three because every one of them is a
 * boundary: latitude exactly 84, longitude exactly 180, and latitude past the
 * band UTM covers at all.
 */
test("the known coordinate gaps are still exactly these three", () => {
  // 1. The Svalbard zone exception. The utm package applies it up to and
  //    INCLUDING 84 degrees; convert.js stops just below. Only longitudes in
  //    the exception's own ranges show it -- elsewhere the regular grid
  //    happens to give the same answer.
  assert.equal(toUtm(84, 20).zone, 34, "the Svalbard upper bound was fixed");
  assert.equal(
    fixtures.coordinates.every((item) => item.lat !== 84),
    true,
    "a coordinate case now sits on 84, so this belongs in the main check",
  );

  // 2. Longitude exactly 180. The utm package folds it to -180 and returns
  //    zone 1; convert.js computes zone 61, which does not exist. The
  //    projected metres agree either way, so only the printed zone is wrong.
  assert.equal(toUtm(0, 180).zone, 61, "the antimeridian zone was fixed");
  assert.equal(toUtm(0, -180).zone, 1);

  // 3. MGRS outside UTM's latitude band. Python's C library falls back to the
  //    polar UPS grid; convert.js implements UTM only and gives up. This is
  //    the one the table row check has to excuse.
  assert.equal(toUtm(85, 20), null);
  assert.equal(toMgrs(85, 20), null, "polar MGRS arrived; the table check can stop excusing it");
  assert.equal(toMgrs(-85, 20), null);
  // Right up to the edge the two still agree, which is what makes the gap a
  // gap rather than a general failure.
  assert.equal(toMgrs(83.9, 20), "33XWP5924519502");
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
