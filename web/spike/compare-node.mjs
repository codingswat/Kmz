// The KML parser needs a DOM, which Node lacks. For this comparison the
// parsed result is injected from the fixture the Python side produced, so
// everything downstream -- geometry, table, workbook -- is exercised for
// real. The parser itself is cross-checked in a browser, where it runs.
import { readFileSync, writeFileSync } from "node:fs";
import { measure } from "../src/geometry.js";
import { buildTableRows } from "../src/table.js";
import { buildBatchWorkbook } from "../src/workbook.js";

const fixture = JSON.parse(readFileSync(new URL("./parser-expected.json", import.meta.url)));

const points = [];
const areas = [];
for (const [name, doc] of Object.entries(fixture)) {
  for (const p of doc.points) points.push({ ...p, sourceFile: name });
  for (const a of doc.areas) {
    areas.push(measure({
      ...a,
      outer: a.outer.map((c) => ({ ...c, name: a.name, sourceFile: name })),
      holes: a.holes.map((h) => h.map((c) => ({ ...c, name: a.name, sourceFile: name }))),
      sourceFile: name,
    }));
  }
}

writeFileSync(process.argv[2], buildBatchWorkbook({
  rows: buildTableRows(points), areas, issues: [],
}));
console.log(`wrote ${process.argv[2]}: ${points.length} points, ${areas.length} areas`);
