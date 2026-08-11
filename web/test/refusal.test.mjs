/**
 * Both versions must refuse the same shapes with the same words.
 *
 * A refusal is not an internal error code. It is printed into a merged banner
 * across the top of an area on the Areas sheet, and it is the only thing that
 * tells a reader why a polygon has no size. Two versions of the tool giving
 * two different reasons for the same polygon is the same defect as two
 * different numbers, and harder to spot.
 *
 * cross-check.test.mjs compares the reason for every shape in the fixture,
 * which catches a wording change to a refusal that some shape reaches. This
 * file covers what that cannot: a refusal ADDED to one implementation and not
 * the other. Nothing in the fixture reaches a reason that does not exist yet,
 * so the two lists are compared directly.
 *
 *     node --test web/test/
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { polygonArea, REFUSALS } from "../src/geometry.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "fixtures.json"), "utf8"));
const refusals = fixtures.refusals;

/** A template as a pattern, with `{count}` and friends standing for a value. */
function asPattern(template) {
  const escaped = template.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // The escape above turned "{count}" into "\{count\}"; each becomes ".+".
  return new RegExp(`^${escaped.replace(/\\\{\w+\\\}/g, ".+")}$`);
}

test("the two implementations know the same refusals", () => {
  // In order, not as sets: the lists are short, hand-maintained in two
  // languages, and reading them side by side is how anyone checks them.
  assert.deepEqual(REFUSALS, refusals.templates);
});

test("the refusal comparison is looking at real refusals", () => {
  assert.ok(REFUSALS.length >= 6, `only ${REFUSALS.length} refusals`);
  assert.equal(new Set(REFUSALS).size, REFUSALS.length, "a refusal is listed twice");
  for (const template of REFUSALS) {
    assert.equal(typeof template, "string");
    assert.ok(template.length > 10, `${JSON.stringify(template)} is barely a sentence`);
  }
});

test("every refusal the code knows is one some shape actually reaches", () => {
  // The list above could agree perfectly and describe reasons neither version
  // can produce. Each template has to be matched by a reason some fixture
  // shape genuinely provoked, or it is dead wording that has stopped being
  // checked against anything.
  const unreached = REFUSALS.filter(
    (template) => !refusals.exercised.some((reason) => asPattern(template).test(reason)),
  );
  assert.deepEqual(
    unreached,
    [],
    `no fixture shape produces: ${unreached.map((t) => JSON.stringify(t)).join(", ")}`,
  );
});

test("every refusal a shape reaches is one of the listed ones", () => {
  // The other direction: a reason produced by wording written at the point of
  // refusal rather than taken from the list would show up here.
  for (const reason of refusals.exercised) {
    const matches = REFUSALS.filter((template) => asPattern(template).test(reason));
    assert.equal(
      matches.length,
      1,
      `${JSON.stringify(reason)} matches ${matches.length} of the listed refusals`,
    );
  }
});

test("the browser reaches those refusals by producing the same strings", () => {
  // The lists agreeing is not the same as the code using them. Every reason
  // Python's shapes produced has to come back out of polygonArea, spelled the
  // same way -- including the numbers filled into the templates.
  const produced = new Set();
  for (const item of fixtures.areas) {
    const problem = polygonArea(item.outer, item.holes).problem;
    if (problem !== null) produced.add(problem);
  }
  assert.deepEqual([...produced].sort(), refusals.exercised);
});

test("no refusal is spelled out anywhere but the list", () => {
  // The templates only stay comparable while they are the single source of
  // the wording. A `measurement(null, "…")` written at a return would pass
  // every test above and be invisible to the one in Python.
  const source = readFileSync(join(here, "..", "src", "geometry.js"), "utf8");
  const literal = /measurement\(\s*(?:null|[^,)]*)\s*,\s*["'`]/.exec(source);
  assert.equal(
    literal,
    null,
    `a refusal is written as a literal rather than taken from the list: ${literal?.[0]}`,
  );
});
