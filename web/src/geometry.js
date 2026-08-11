/**
 * Measuring shapes.
 *
 * A port of kmz_points/geometry.py. Separate from convert.js, which converts
 * one point at a time and knows nothing about how points relate. Everything
 * here is pure and nothing throws: an unmeasurable shape comes back carrying
 * the reason, so one bad polygon can never abort a batch.
 *
 * The area is FLAT MAP AREA -- the shape as traced on a map, not surface area
 * following the terrain. A sloping hillside's true surface is larger than its
 * footprint, and the elevation data needed to compute that is not in a KML.
 */

import { exactFixed, toUtm } from "./convert.js";

const UTM_MIN_LAT = -80.0;
const UTM_MAX_LAT = 84.0;

// Forcing every corner into a single zone is what keeps the grid consistent,
// but distortion grows with distance from that zone's central meridian. A
// zone is 6 degrees wide, so beyond that span the projection stops being
// trustworthy and a refusal beats a confident wrong number.
const MAX_LONGITUDE_SPAN = 6.0;

const SQUARE_METRES_PER_HECTARE = 10000.0;
const SQUARE_METRES_PER_SQUARE_KM = 1000000.0;

// Every reason a shape can be refused. Copied verbatim from kmz_points/
// geometry.py's REFUSALS -- these are the words an end user reads out of a
// spreadsheet banner, so the two implementations have to agree on them the
// same way they agree on a number. web/test/refusal.test.mjs compares the two
// lists, and a reason added on one side alone fails the build.
export const NOT_ENOUGH_CORNERS = "needs at least 3 distinct corners, found {count}";
export const OUTSIDE_UTM_RANGE =
  "lies outside the range UTM covers ({low} to {high} degrees latitude)";
export const LONGITUDE_TOO_WIDE =
  "spans {span} degrees of longitude, more than the {limit} a single UTM zone covers";
export const COULD_NOT_PROJECT = "could not be projected";
export const COULD_NOT_MEASURE = "could not be measured";
export const HOLES_COVER_EVERYTHING = "its holes cover the whole shape, leaving no area";

export const REFUSALS = [
  NOT_ENOUGH_CORNERS,
  OUTSIDE_UTM_RANGE,
  LONGITUDE_TOO_WIDE,
  COULD_NOT_PROJECT,
  COULD_NOT_MEASURE,
  HOLES_COVER_EVERYTHING,
];

/**
 * Fill a refusal template, the way Python's str.format fills the same one.
 *
 * Going through the template rather than writing the sentence out again is
 * what keeps the two implementations honest: there is one copy of the wording
 * per language and a test that compares them, instead of a sentence spelled
 * out at each `return`.
 */
function refuse(template, values = {}) {
  return template.replace(/\{(\w+)\}/g, (_match, key) => values[key]);
}

/** An area, or the reason there isn't one. */
export function measurement(squareMetres, problem = null) {
  return {
    squareMetres,
    problem,
    hectares: squareMetres === null ? null : squareMetres / SQUARE_METRES_PER_HECTARE,
    squareKilometres:
      squareMetres === null ? null : squareMetres / SQUARE_METRES_PER_SQUARE_KM,
  };
}

/**
 * Drop consecutive duplicates, including the repeated closing corner.
 *
 * KML writes rings closed, repeating the first coordinate last. Counting that
 * as a real corner adds a zero-width sliver to the shoelace sum.
 */
export function distinctCorners(ring) {
  const kept = [];
  for (const point of ring) {
    const last = kept[kept.length - 1];
    if (last && last.lat === point.lat && last.lon === point.lon) continue;
    kept.push(point);
  }
  while (
    kept.length > 1 &&
    kept[0].lat === kept[kept.length - 1].lat &&
    kept[0].lon === kept[kept.length - 1].lon
  ) {
    kept.pop();
  }
  return kept;
}

/**
 * Area of a simple polygon from its projected corners.
 *
 * Absolute, because the signed sum is negative for one winding direction and
 * a shape's area does not depend on which way round it was drawn.
 */
function shoelace(projected) {
  let total = 0;
  for (let i = 0; i < projected.length; i += 1) {
    const [x1, y1] = projected[i];
    const [x2, y2] = projected[(i + 1) % projected.length];
    total += x1 * y2 - x2 * y1;
  }
  return Math.abs(total) / 2;
}

function project(ring, zone) {
  return ring.map((point) => {
    const utm = toUtm(point.lat, point.lon, zone);
    return utm ? [utm.easting, utm.northing] : null;
  });
}

/** Why this ring cannot be measured, or null if it can. */
export function ringProblem(ring) {
  if (ring.length < 3) {
    return refuse(NOT_ENOUGH_CORNERS, { count: ring.length });
  }

  const latitudes = ring.map((p) => p.lat);
  if (Math.min(...latitudes) < UTM_MIN_LAT || Math.max(...latitudes) > UTM_MAX_LAT) {
    return refuse(OUTSIDE_UTM_RANGE, { low: UTM_MIN_LAT, high: UTM_MAX_LAT });
  }

  const longitudes = ring.map((p) => p.lon);
  const span = Math.max(...longitudes) - Math.min(...longitudes);
  if (span > MAX_LONGITUDE_SPAN) {
    // exactFixed, not toFixed: a span of exactly 6.25 degrees is a tie at one
    // decimal, and toFixed would round it away from zero to "6.3" where
    // Python's "{:.1f}" rounds it to even and says "6.2".
    return refuse(LONGITUDE_TOO_WIDE, {
      span: exactFixed(span, 1),
      limit: MAX_LONGITUDE_SPAN,
    });
  }

  return null;
}

/**
 * Flat map area of a polygon, holes subtracted.
 *
 * Every corner -- outer and holes alike -- is projected in the zone of the
 * outer ring's centre. Letting each corner pick its own zone would mix two
 * different grids and produce a meaningless number for any shape near a zone
 * boundary.
 */
export function polygonArea(outer, holes = []) {
  const ring = distinctCorners(outer);

  const problem = ringProblem(ring);
  if (problem !== null) return measurement(null, problem);

  const lons = ring.map((p) => p.lon);
  const lats = ring.map((p) => p.lat);
  const centreLon = (Math.max(...lons) + Math.min(...lons)) / 2;
  const centreLat = (Math.max(...lats) + Math.min(...lats)) / 2;

  // Only the centre falling outside what UTM accepts is "could not be
  // projected". A corner that will not project is "could not be measured",
  // because that is the branch Python raises out of -- the two are separate
  // sentences a reader sees, so they have to divide the cases the same way.
  const centre = toUtm(centreLat, centreLon);
  if (!centre) return measurement(null, refuse(COULD_NOT_PROJECT));
  const zone = centre.zone;

  const outerProjected = project(ring, zone);
  if (outerProjected.some((corner) => corner === null)) {
    return measurement(null, refuse(COULD_NOT_MEASURE));
  }

  let total = shoelace(outerProjected);

  for (const hole of holes) {
    const holeRing = distinctCorners(hole);
    // A hole too broken to measure simply is not subtracted.
    if (ringProblem(holeRing) !== null) continue;
    const holeProjected = project(holeRing, zone);
    // But a hole that passes those checks and still will not project is a
    // different thing, and it refuses the whole shape. Skipping it silently
    // returned a confident number where Python refused -- a corner past the
    // antimeridian got dropped and the area came back as if the hole were
    // not there.
    if (holeProjected.some((corner) => corner === null)) {
      return measurement(null, refuse(COULD_NOT_MEASURE));
    }
    total -= shoelace(holeProjected);
  }

  if (total <= 0) {
    return measurement(null, refuse(HOLES_COVER_EVERYTHING));
  }

  return measurement(total);
}

/** An area paired with its size, ready to be written out. */
export function measure(area) {
  return { area, measurement: polygonArea(area.outer, area.holes || []) };
}
