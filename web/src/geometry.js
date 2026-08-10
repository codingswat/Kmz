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

import { toUtm } from "./convert.js";

const UTM_MIN_LAT = -80.0;
const UTM_MAX_LAT = 84.0;

// Forcing every corner into a single zone is what keeps the grid consistent,
// but distortion grows with distance from that zone's central meridian. A
// zone is 6 degrees wide, so beyond that span the projection stops being
// trustworthy and a refusal beats a confident wrong number.
const MAX_LONGITUDE_SPAN = 6.0;

const SQUARE_METRES_PER_HECTARE = 10000.0;
const SQUARE_METRES_PER_SQUARE_KM = 1000000.0;

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
    return `needs at least 3 distinct corners, found ${ring.length}`;
  }

  const latitudes = ring.map((p) => p.lat);
  if (Math.min(...latitudes) < UTM_MIN_LAT || Math.max(...latitudes) > UTM_MAX_LAT) {
    return (
      "lies outside the range UTM covers " +
      `(${UTM_MIN_LAT} to ${UTM_MAX_LAT} degrees latitude)`
    );
  }

  const longitudes = ring.map((p) => p.lon);
  const span = Math.max(...longitudes) - Math.min(...longitudes);
  if (span > MAX_LONGITUDE_SPAN) {
    return (
      `spans ${span.toFixed(1)} degrees of longitude, more than the ` +
      `${MAX_LONGITUDE_SPAN} a single UTM zone covers`
    );
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

  const centre = toUtm(centreLat, centreLon);
  if (!centre) return measurement(null, "could not be projected");
  const zone = centre.zone;

  const outerProjected = project(ring, zone);
  if (outerProjected.some((corner) => corner === null)) {
    return measurement(null, "could not be projected");
  }

  let total = shoelace(outerProjected);

  for (const hole of holes) {
    const holeRing = distinctCorners(hole);
    // A hole too broken to measure simply is not subtracted.
    if (ringProblem(holeRing) !== null) continue;
    const holeProjected = project(holeRing, zone);
    if (holeProjected.some((corner) => corner === null)) continue;
    total -= shoelace(holeProjected);
  }

  if (total <= 0) {
    return measurement(null, "its holes cover the whole shape, leaving no area");
  }

  return measurement(total);
}

/** An area paired with its size, ready to be written out. */
export function measure(area) {
  return { area, measurement: polygonArea(area.outer, area.holes || []) };
}
