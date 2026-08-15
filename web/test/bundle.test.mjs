/**
 * The single-file build must be current and usable.
 *
 * kmz-extractor.html is committed, because the point of it is that someone
 * can download one file and open it. A committed build goes stale the moment
 * anyone edits src/ and forgets to rebuild, and a stale one is worse than
 * none: it looks fine and quietly does the old thing.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const web = dirname(here);
const built = join(web, "kmz-extractor.html");

function scriptOf(html) {
  return html.slice(html.indexOf("<script>") + "<script>".length, html.lastIndexOf("</script>"));
}

test("the committed single file matches a fresh build", () => {
  const committed = readFileSync(built, "utf8");
  // Build somewhere else and compare. Rebuilding over the committed file
  // made this check self-healing -- it reported a real staleness once, then
  // passed on the very next run because the first run had fixed it -- and it
  // left a tracked file modified after merely running the tests.
  const scratch = mkdtempSync(join(tmpdir(), "kmz-bundle-"));
  try {
    const fresh = join(scratch, "kmz-extractor.html");
    execFileSync(process.execPath, [join(web, "build.mjs"), fresh], { stdio: "pipe" });
    assert.equal(
      readFileSync(fresh, "utf8"),
      committed,
      "kmz-extractor.html is out of date — run `node web/build.mjs` and commit the result",
    );
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("the bundle is valid JavaScript", () => {
  // A syntax error here would be invisible until someone opened the file:
  // the page would render and do nothing, which is exactly the failure this
  // build exists to fix.
  const code = scriptOf(readFileSync(built, "utf8"));
  assert.doesNotThrow(() => new Function(code), "the bundled script does not parse");
});

test("the bundle has no imports left to resolve", () => {
  // An import surviving the build would work over http and fail over file://,
  // which is the whole reason this file exists.
  const code = scriptOf(readFileSync(built, "utf8"));
  assert.ok(!/^\s*import\s/m.test(code), "an import survived the build");
  assert.ok(!/^\s*export\s/m.test(code), "an export survived the build");
  assert.ok(!code.includes('"./src/'), "the bundle still points at src/");
});

test("every module made it into the bundle", () => {
  const code = scriptOf(readFileSync(built, "utf8"));
  for (const name of [
    "zip.js", "xlsx.js", "convert.js", "unzip.js", "archive.js",
    "geometry.js", "table.js", "workbook.js", "kml.js", "pipeline.js",
  ]) {
    assert.ok(code.includes(`__modules["${name}"]`), `${name} is missing from the bundle`);
  }
});

test("both versions carry the no-warranty notice", () => {
  // The tool prints coordinates, areas and distances that someone may act on,
  // and it is published with no licence warranty behind it. The notice has to
  // survive the build, so it is checked in the template and in the single
  // file -- editing one and forgetting the other is the failure to catch.
  for (const [name, file] of [
    ["the template", join(web, "index.html")],
    ["the single file", built],
  ]) {
    const html = readFileSync(file, "utf8");
    assert.match(html, /No warranty\./, `${name} has lost the notice`);
    assert.match(html, /check them against\s+an authoritative source/, `${name} has lost the advice`);
  }
});

test("the page fetches nothing from the network", () => {
  // The tool has to work offline, and a page that phones out is also a page
  // that leaks who is using it. This checks for things the browser would
  // actually request -- not for the string "http", which appears legitimately
  // as the xlsx format's XML namespace identifiers. Those are names, never
  // fetched, and an earlier version of this test failed on them.
  const html = readFileSync(built, "utf8");

  assert.ok(!/<script[^>]+\bsrc=/i.test(html), "the page loads an external script");
  assert.ok(!/<link[^>]+\bhref=/i.test(html), "the page loads an external stylesheet");
  assert.ok(!/<img[^>]+\bsrc=/i.test(html), "the page loads an external image");

  const code = scriptOf(html);
  assert.ok(!/\bfetch\s*\(/.test(code), "the bundle calls fetch()");
  assert.ok(!/XMLHttpRequest/.test(code), "the bundle uses XMLHttpRequest");
  assert.ok(!/\bimport\s*\(/.test(code), "the bundle imports at runtime");
});
