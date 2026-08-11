/**
 * The banner above each area must read identically in both versions.
 *
 * It is the one place a measurement is turned into words, and it was never
 * compared: kmz_points/excel.py builds it in area_banner_text and
 * web/src/workbook.js in areaBannerText, and until this file nothing checked
 * that the two agreed. They did not.
 *
 * Python's `format(x, ',.3f')` and JavaScript's `toLocaleString("en-US", …)`
 * are not the same function, and they part ways twice over. The workbook
 * comparison could not have caught it: a banner is one merged string, and
 * both sides were writing the string each believed in.
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

import { measurement } from "../src/geometry.js";
import { areaBannerText, groupedFixed } from "../src/workbook.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));

/** What the browser would show for one of Python's area cases. */
function bannerFor(item) {
  return areaBannerText({
    area: { name: item.name, outer: item.outer, holes: item.holes || [] },
    measurement: measurement(
      item.squareMetres,
      item.problem ?? null,
      item.perimeterMetres ?? null,
    ),
  });
}

test("every measured area's banner matches Python's word for word", () => {
  assert.equal(
    fixtures.banners.length,
    fixtures.areas.length,
    "the fixture has a different number of banners and areas",
  );

  for (const [index, item] of fixtures.areas.entries()) {
    assert.equal(bannerFor(item), fixtures.banners[index], `area ${index} (${item.name})`);
  }
});

test("banners built from sizes chosen to break a rounder still match", () => {
  // The areas above are measured polygons, so their three numbers are
  // whatever the shoelace sum produced. These sizes were picked instead --
  // exact ties at nought, three and six decimals, and values stored just
  // below the decimal they print as.
  for (const item of fixtures.bannerNumbers) {
    assert.equal(bannerFor(item), item.text, `${item.name}`);
  }
});

test("groupedFixed reproduces Python's format(x, ',.Nf') exactly", () => {
  for (const item of fixtures.groupedFixed) {
    assert.equal(
      groupedFixed(item.value, item.places),
      item.text,
      `${item.value} to ${item.places} places`,
    );
  }
});

test("those values really are the ones a naive rounder gets wrong", () => {
  // Without this, the three tests above could all be passing on values that
  // never distinguished the implementations -- which is exactly the state
  // this file was written to end. Both of the obvious JavaScript answers are
  // run against the fixture here, and both must be shown to fail on it.
  const naive = {
    toLocaleString: (value, places) =>
      value.toLocaleString("en-US", {
        minimumFractionDigits: places,
        maximumFractionDigits: places,
      }),
    // toFixed does at least round the stored double, so it only gets the
    // exact ties wrong. It has no grouping, so only ungrouped values count.
    toFixed: (value, places) => value.toFixed(places),
  };

  for (const [name, render] of Object.entries(naive)) {
    const wrong = fixtures.groupedFixed.filter((item) => {
      if (name === "toFixed" && item.text.includes(",")) return false;
      // Neither renders a value large enough to go exponential, and Python's
      // spelling of the specials is its own business.
      if (!Number.isFinite(item.value) || Math.abs(item.value) >= 1e21) return false;
      return render(item.value, item.places) !== item.text;
    });

    // Counted per precision rather than in total: a fixture that lost its
    // ties at six places would still pass a total, on the strength of the
    // much commoner disagreements at nought.
    for (const places of [0, 3, 6]) {
      const caught = wrong.filter((item) => item.places === places).length;
      assert.ok(caught >= 2, `${name} was caught out only ${caught} times at ${places} places`);
    }
  }
});

test("the adversarial banners really are adversarial", () => {
  // The same proof one level up: at least one banner in the fixture is one
  // the old implementation would have got wrong, at each of the three
  // precisions a banner uses.
  const old = (value, places) =>
    value.toLocaleString("en-US", {
      minimumFractionDigits: places,
      maximumFractionDigits: places,
    });

  const oldBanner = (item) => {
    const size = item.squareMetres;
    return (
      `${item.name} — ${old(size, 0)} m² · ${old(size / 1e4, 3)} ha · ` +
      `${old(size / 1e6, 6)} km² · ${old(item.perimeterMetres, 0)} m perimeter · 4 corners`
    );
  };

  const wrong = fixtures.bannerNumbers.filter((item) => oldBanner(item) !== item.text);
  assert.ok(wrong.length >= 3, `only ${wrong.length} banners would have been wrong`);

  // And name the three precisions explicitly, so a fixture that lost its ties
  // at one of them cannot pass on the strength of the other two.
  const brokenAt = (places, divisor) =>
    fixtures.bannerNumbers.some(
      (item) => old(item.squareMetres / divisor, places) !== groupedFixed(item.squareMetres / divisor, places),
    );
  assert.ok(brokenAt(0, 1), "no banner size is a tie at nought decimals");
  assert.ok(brokenAt(3, 1e4), "no banner size is a tie at three decimals");
  assert.ok(brokenAt(6, 1e6), "no banner size is a tie at six decimals");
});

test("an unmeasurable area's banner gives the reason, identically", () => {
  const refused = fixtures.areas
    .map((item, index) => ({ item, expected: fixtures.banners[index] }))
    .filter(({ item }) => item.squareMetres === null);

  assert.ok(refused.length > 3, `only ${refused.length} refused areas in the fixture`);
  for (const { item, expected } of refused) {
    assert.ok(expected.includes("area not measured"), `${item.name}: not a refusal banner`);
    assert.equal(bannerFor(item), expected, `${item.name}`);
  }
});
