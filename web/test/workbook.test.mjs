/**
 * The browser's workbook must say the same thing as Python's.
 *
 * Not the same bytes -- openpyxl and a hand-written writer will never agree on
 * those, and demanding it would fail on every run while proving nothing. What
 * is compared is what a person opening the file sees: the sheets, every cell's
 * value, type and number format, the merges, the column widths and the freeze.
 * Both sides are reduced to that shape by kmz_points/workbook_facts.py and
 * web/test/workbook-facts.mjs; see either for what is deliberately left out.
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

import { measure } from "../src/geometry.js";
import { buildTableRows } from "../src/table.js";
import { buildBatchSheets } from "../src/workbook.js";
import { firstDifference, workbookFacts } from "./workbook-facts.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));

/**
 * The sample batch, rebuilt from the parse Python recorded.
 *
 * Taking the parsed points and areas from the fixture rather than reparsing
 * exercises geometry, the table and the writer without needing a DOM -- the
 * KML parser is the one part that cannot run in Node, and it is checked in a
 * browser instead.
 */
function sampleBatch() {
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

  return { rows: buildTableRows(points), areas, issues: [] };
}

test("the produced workbook lays out identically to Python's", () => {
  const facts = workbookFacts(buildBatchSheets(sampleBatch()));
  const expected = fixtures.batch.workbookFacts;

  const complaint = firstDifference(facts, expected);
  if (complaint) assert.fail(complaint);

  // The line above names the one cell that went wrong, which is all anyone
  // reading a failure wants. This catches anything it does not know to look at.
  assert.deepEqual(facts, expected);
});

test("the comparison is looking at a whole workbook", () => {
  // Two empty descriptions are also identical. This is what stops the test
  // above from passing because nothing reached it -- the batch must be the
  // one Python exported, and the fixture must carry both sheets in full.
  const { rows, areas } = sampleBatch();
  assert.equal(rows.length, fixtures.batch.summary.pointsExtracted);
  assert.equal(areas.length, fixtures.batch.summary.areasExtracted);

  const expected = fixtures.batch.workbookFacts;
  assert.deepEqual(
    expected.sheets.map((sheet) => sheet.name),
    ["Points", "Areas"],
  );

  const cells = expected.sheets.map((sheet) => sheet.cells.length);
  assert.ok(Math.min(...cells) > 100, `too few cells to be the batch: ${cells}`);
  assert.ok(
    expected.sheets.every((sheet) => sheet.merges.length && sheet.columnWidths.length),
    "a sheet reported no merges or no column widths",
  );
});
