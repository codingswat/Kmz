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
      // A refused shape has no perimeter either. Reporting one would say the
      // outline is trustworthy when the reason it was refused is that it is
      // not.
      assert.equal(result.perimeterMetres, null, `${item.name} should have no perimeter`);
      // The whole reason, not its first thirty characters. Comparing a prefix
      // hid a live divergence for as long as it existed: Python interpolated
      // the caught exception's text and the browser did not, and every one of
      // those strings agrees for far longer than thirty characters.
      assert.equal(result.problem, item.problem, `${item.name}: different reason`);
      continue;
    }

    assert.ok(result.squareMetres !== null, `${item.name} should be measurable`);
    // A relative tolerance, not equality: the two languages' libm differ in
    // the last bit of a sin or an atan2, which showed up as ~1e-16 and is not
    // a disagreement about the answer. The formula either side of those calls
    // is the same one, so this is noise rather than a tolerance being spent.
    const relative = Math.abs(result.squareMetres - item.squareMetres) / item.squareMetres;
    assert.ok(relative < 1e-6, `${item.name}: ${result.squareMetres} vs ${item.squareMetres}`);

    const perimeterOff =
      Math.abs(result.perimeterMetres - item.perimeterMetres) / item.perimeterMetres;
    assert.ok(
      perimeterOff < 1e-6,
      `${item.name}: perimeter ${result.perimeterMetres} vs ${item.perimeterMetres}`,
    );
  }
});

/**
 * The measurement is on the ellipsoid, and the fixture has to prove it.
 *
 * A sweep over 150 shapes passes just as happily on two implementations that
 * are wrong in the same way, so these are the shapes the sweep would not tell
 * you about by name: the two the projection used to refuse outright, and the
 * one whose corners sit either side of the antimeridian.
 */
test("the shapes the projection could not measure are measured now", () => {
  const named = (name) => fixtures.areas.find((item) => item.name === name);

  for (const name of ["polar", "close to the pole", "spans 6.25 degrees"]) {
    const item = named(name);
    assert.ok(item, `the fixture lost "${name}"`);
    assert.ok(item.squareMetres > 0, `${name} should now measure`);
    assert.equal(polygonArea(item.outer, item.holes).problem, null);
  }

  // Straddling 180 degrees, where a bounding box in raw longitude would read
  // 359.98 degrees wide and every step but one would be measured the long way
  // round the world.
  const across = named("across the antimeridian");
  const here = polygonArea(across.outer, across.holes);
  assert.ok(here.squareMetres > 0);
  // 0.02 by 0.01 degrees at 10 degrees north, which is about 2.4 km².
  assert.ok(here.squareMetres > 2.4e6 && here.squareMetres < 2.45e6, `${here.squareMetres}`);
});

/**
 * The two coordinates the browser used to get wrong, asserted positively.
 *
 * Both were pinned here as known defects for as long as they stood, because
 * they change numbers a workbook shows and that is a change to make
 * deliberately. They are fixed now, and the coordinate cases above carry
 * latitude 84 and longitude 180 as a matter of course, so the sweep covers
 * them too -- these assertions stay because a sweep says which coordinate
 * disagreed and this says what was meant to happen there.
 */
test("the boundary coordinates agree with Python", () => {
  // Both of these were gaps until the sweep above was widened enough to name
  // them. They are asserted positively now, against the values the utm
  // package actually returns, so a regression reads as a disagreement rather
  // than as a pin nobody removed.

  // The Svalbard exception runs up to and INCLUDING 84 degrees. Only
  // longitudes inside the exception's own ranges show it -- elsewhere the
  // regular grid happens to give the same answer, which is why hundreds of
  // random coordinates never caught this.
  assert.equal(toUtm(84, 20).zone, 33);
  assert.equal(toUtm(84, 20).band, "X");

  // Longitude exactly 180 folds to -180 and lands in zone 1. Computing it
  // straight gave zone 61, and there are only 60.
  assert.equal(toUtm(0, 180).zone, 1);
  assert.equal(toUtm(0, -180).zone, 1);
  assert.equal(Math.round(toUtm(0, 180).easting), 166021);
  assert.equal(Math.round(toUtm(0, 180).northing), 0);
});

/**
 * The angle from a central meridian, when the zone is across the antimeridian.
 *
 * `forceZone` has no caller left: geometry.js used it to project every corner
 * of a shape into the single zone of that shape's centre, and geometry.js no
 * longer projects anything. What it still covers is the only place the angle
 * from a central meridian can exceed half a turn -- a point at -180 forced
 * into zone 60 sits 357 degrees from that zone's meridian, and the utm package
 * folds it to 3 before projecting -- so the parameter and this test are kept
 * against the day something forces a zone again. The fixture sweep cannot
 * reach it, since Python's to_utm never forces one, so the reference values
 * are taken by hand:
 *
 *     .venv/bin/python -c "import utm; print(utm.from_latlon(0.0, -180.0, force_zone_number=60))"
 */
test("a forced zone across the antimeridian agrees with Python", () => {
  // Both directions, because only one of them can be got wrong. JavaScript's
  // `%` keeps the sign of its LEFT operand where Python's takes the sign of
  // its right, so a fold written as `(x + pi) % (2pi) - pi` folds +357 degrees
  // to -3 correctly and leaves -357 exactly where it was.
  const eastward = toUtm(0, 180, 1);
  assert.equal(Math.round(eastward.easting), 166021);
  assert.equal(Math.round(eastward.northing), 0);

  const westward = toUtm(0, -180, 60);
  assert.equal(Math.round(westward.easting), 833979);
  assert.equal(Math.round(westward.northing), 0);

  // And once below the equator, where the false northing is added on top.
  const southward = toUtm(-33, -180, 60);
  assert.equal(Math.round(southward.easting), 780300);
  assert.equal(Math.round(southward.northing), 6344714);
});

/**
 * The polar caps, which were the last gap and are a gap no longer.
 *
 * This was pinned as a known defect for as long as convert.js implemented UTM
 * and nothing else: past the band UTM covers, Python's C library falls back to
 * the UPS grid and returned a reference where the browser returned nothing.
 * The coordinate cases carry the caps now, so the sweep above covers this like
 * anywhere else -- these assertions stay because a sweep tells you which
 * coordinate disagreed and this tells you what was supposed to happen there.
 */
test("the polar grid agrees with Python past UTM's band", () => {
  // UTM really does stop, and both sides agree that it does. That is not the
  // defect and never was -- the projected metres have no zone to belong to.
  assert.equal(toUtm(85, 20), null);
  assert.equal(toUtm(-85, 20), null);

  // MGRS does not stop. In place of a zone number the reference opens with a
  // zone LETTER: Y or Z above 84, A or B below -80.
  assert.equal(toMgrs(85, 20), "ZBB8997778040");
  assert.equal(toMgrs(-85, 20), "BBT8997721959");
  assert.equal(toMgrs(84.5, 20), "ZCB0900225771");
  assert.equal(toMgrs(-80.1, 20), "BFY7682635323");

  // The western half of each cap. Which half a point lands in is decided by
  // its easting rather than by the sign of its longitude, and the two rules
  // part company only on the antimeridian -- where the easting projects onto
  // the dividing line itself, so a western longitude letters as eastern.
  assert.equal(toMgrs(85, -20), "YYB1002278040");
  assert.equal(toMgrs(-85, -20), "AYT1002221959");
  assert.equal(toMgrs(85, 180), "ZAN0000055457");

  // The poles, where the projection collapses onto its origin and longitude
  // stops meaning anything at all.
  assert.equal(toMgrs(90, 0), "ZAH0000000000");
  assert.equal(toMgrs(-90, 20), "BAN0000000000");

  // And the UTM side of the boundary is untouched, which is what says the
  // second grid was added beside the first rather than over it.
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
