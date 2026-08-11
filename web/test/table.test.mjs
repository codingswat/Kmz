/**
 * The two COLUMNS lists must describe the same table.
 *
 * kmz_points/table.py and web/src/table.js each hold a hand-maintained list of
 * columns, and both row builders emit POSITIONAL arrays. Nothing compared them
 * until this file: a column added to one side and not the other does not fail,
 * it shifts every value after it by one and produces two different workbooks
 * that each look plausible. Header, kind, number format and band are compared
 * separately so a failure says which of the four went wrong -- a column moved
 * into a neighbouring band is caught by the last of them and by nothing else.
 *
 * Then the rows themselves, because agreeing on the shape of the table is not
 * the same as agreeing on what goes in it.
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

import { buildTableRows, COLUMNS } from "../src/table.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));
const table = fixtures.table;

// Both languages compute the same formula from the same doubles, but not
// always in the same order, which showed up as differences around 1e-9. That
// is float noise, not a disagreement about the answer; anything larger is.
const TOLERANCE = 1e-9;

function show(value) {
  if (value === undefined) return "nothing";
  return typeof value === "string" ? JSON.stringify(value) : String(value);
}

/** Compare two per-column lists, naming the first index that disagrees. */
function compareColumns(what, actual, expected) {
  const shared = Math.min(actual.length, expected.length);
  for (let index = 0; index < shared; index += 1) {
    if (actual[index] === expected[index]) continue;
    assert.fail(
      `${what}: column ${index} is ${show(actual[index])} in the browser and ` +
        `${show(expected[index])} in Python`,
    );
  }
  if (actual.length !== expected.length) {
    assert.fail(
      `${what}: the browser has ${actual.length} columns and Python has ` +
        `${expected.length}; they first part ways at column ${shared}, where the ` +
        `browser has ${show(actual[shared])} and Python has ${show(expected[shared])}`,
    );
  }
}

test("the two column lists agree on every header", () => {
  compareColumns(
    "headers",
    COLUMNS.map((column) => column.header),
    table.headers,
  );
});

test("the two column lists agree on every cell kind", () => {
  // Kind decides whether a value lands in the sheet as a number or as text,
  // which is the difference between a sortable column and a column of strings
  // that sorts "1000" before "9".
  compareColumns(
    "cell kinds",
    COLUMNS.map((column) => column.kind),
    table.kinds,
  );
});

test("the two column lists agree on every number format", () => {
  // The JS entries leave the key off where there is no format and Python
  // stores None; both mean the same thing, so both become null here.
  compareColumns(
    "number formats",
    COLUMNS.map((column) => column.numberFormat ?? null),
    table.numberFormats,
  );
});

test("every column sits in the same band on both sides", () => {
  // A column that moves one place across a band boundary keeps its header,
  // its kind and its format, and changes which merged title sits above it.
  // This list is the only thing that notices.
  compareColumns(
    "bands",
    COLUMNS.map((column) => column.band.title),
    table.bands,
  );
});

test("the column comparison is looking at a real table", () => {
  // Two empty lists also agree. This is what stops the four tests above from
  // passing because the fixture arrived empty or the module exported nothing.
  assert.ok(COLUMNS.length >= 23, `only ${COLUMNS.length} columns`);
  for (const [what, list] of Object.entries({
    headers: table.headers,
    kinds: table.kinds,
    numberFormats: table.numberFormats,
    bands: table.bands,
  })) {
    assert.equal(list.length, COLUMNS.length, `Python sent ${list.length} ${what}`);
  }
  // Not one list of the same value repeated, which would agree with anything.
  assert.ok(new Set(table.headers).size > 10, "the headers are barely distinct");
  assert.deepEqual([...new Set(table.kinds)].sort(), ["number", "text"]);
  assert.ok(new Set(table.bands).size >= 4, "fewer bands than the sheet has");
});

const MGRS_COLUMN = COLUMNS.findIndex((column) => column.header === "MGRS");
const ZONE_COLUMN = COLUMNS.findIndex((column) => column.header === "UTM Zone");

test("the row builder produces the rows Python produces", () => {
  const points = table.points;
  const rows = buildTableRows(points);
  const expected = table.rows;

  assert.equal(rows.length, expected.length, "a different number of rows");

  for (const [index, row] of rows.entries()) {
    const theirs = expected[index];
    assert.equal(
      row.length,
      theirs.length,
      `row ${index} has ${row.length} values in the browser and ${theirs.length} in Python`,
    );

    for (let column = 0; column < row.length; column += 1) {
      const mine = row[column];
      const python = theirs[column];
      const agree =
        typeof mine === "number" && typeof python === "number"
          ? Math.abs(mine - python) <= TOLERANCE
          : mine === python;
      if (agree) continue;

      // The header alone does not identify a column -- "longitude" appears in
      // two bands -- so the index and the band come too.
      const { header, band } = COLUMNS[column];
      assert.fail(
        `row ${index} (${show(points[index].name)}), column ${column} ` +
          `"${header}" in band "${band.title}": the browser has ${show(mine)}, ` +
          `Python has ${show(python)}`,
      );
    }
  }

  // The MGRS column used to be excused on exactly these rows: past UTM's band
  // Python returned a polar reference and the browser returned nothing. The
  // loop above compares them like any other cell now, so what is left worth
  // asserting is that such rows still exist for it to compare, and that they
  // carry a reference rather than the blank their UTM neighbours carry.
  const polar = expected.filter((theirs) => theirs[ZONE_COLUMN] === "");
  assert.ok(polar.length >= 2, `expected rows past UTM's band, found ${polar.length}`);
  assert.ok(
    polar.every((theirs) => theirs[MGRS_COLUMN] !== ""),
    "a row past UTM's band has no MGRS reference, so the polar grid is untested here",
  );
});

test("the row comparison is looking at real points", () => {
  // Zero rows compare equal to zero rows. The fixture has to carry the whole
  // spread: the sample batch, the awkward coordinates, and the polar points
  // that are what reach the rows where the UTM columns stay empty.
  assert.ok(table.points.length > 50, `only ${table.points.length} points`);
  assert.ok(
    new Set(table.points.map((p) => p.sourceFile)).size >= 4,
    "the points all came from one file",
  );

  const zoneColumn = COLUMNS.findIndex((c) => c.header === "UTM Zone");
  const zones = new Set(table.rows.map((row) => row[zoneColumn]));
  assert.ok(zones.has(""), "no point outside UTM, so the empty columns are untested");
  assert.ok(zones.size > 5, `only ${zones.size} distinct UTM zones`);

  const altitudes = new Set(table.points.map((p) => p.alt));
  assert.ok(altitudes.has(null) && altitudes.size > 2, "altitude is barely varied");
});
