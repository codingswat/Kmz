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
 *
 * Measurement is on the ELLIPSOID, not on a projection. This is a line-for-
 * line port of the Python: the same authalic-sphere excess for area and the
 * same Vincenty inverse for perimeter, written out here rather than reached
 * for from a library. That is the point of it -- running the SAME formula in
 * both languages makes parity exact by construction rather than something to
 * be achieved and policed, which vendoring 780 lines of third-party numerics
 * into this file would not have done. The two implementations agree to 1e-11
 * across every shape in the fixture, and what is left is the last bit of a
 * `sin` rather than a decision either of them made.
 */

const SEMI_MAJOR = 6378137.0;
const FLATTENING = 1 / 298.257223563;
const SEMI_MINOR = SEMI_MAJOR * (1 - FLATTENING);
const ECCENTRICITY_SQUARED = FLATTENING * (2 - FLATTENING);
const ECCENTRICITY = Math.sqrt(ECCENTRICITY_SQUARED);

/**
 * The area function q, whose value at the pole scales the whole sphere.
 *
 * q(sin lat) is proportional to the area of the ellipsoid between the equator
 * and that latitude, so a latitude mapped by q/q(1) keeps areas rather than
 * angles -- which is the whole trick.
 */
function authalicQ(sinLat) {
  return (
    (1 - ECCENTRICITY_SQUARED) *
    (sinLat / (1 - ECCENTRICITY_SQUARED * sinLat * sinLat) -
      (1 / (2 * ECCENTRICITY)) *
        Math.log((1 - ECCENTRICITY * sinLat) / (1 + ECCENTRICITY * sinLat)))
  );
}

const Q_AT_POLE = authalicQ(1.0);
// The sphere with WGS-84's surface area: 6371007.1809 m.
const AUTHALIC_RADIUS = SEMI_MAJOR * Math.sqrt(Q_AT_POLE / 2);

const RADIANS_PER_DEGREE = Math.PI / 180;

/** Geodetic latitude mapped onto the sphere of equal area. */
function authalicLatitude(latDegrees) {
  const ratio = authalicQ(Math.sin(latDegrees * RADIANS_PER_DEGREE)) / Q_AT_POLE;
  // Clamped because the ratio is 1 at the pole to within rounding, and asin
  // of 1.0000000000000002 is NaN.
  return Math.asin(Math.max(-1.0, Math.min(1.0, ratio)));
}

// Vincenty converges in a handful of iterations for anything this tool
// measures. The cap is there so a pathological pair cannot spin forever, not
// because it is expected to be reached.
const VINCENTY_ITERATIONS = 200;
const VINCENTY_TOLERANCE = 1e-12;

// Both of these are asserted against the Python constants of the same name --
// see web/test/refusal.test.mjs. A ceiling that drifted between the
// implementations would refuse a shape in one and measure it in the other,
// which is the failure this file is arranged to prevent.
//
// THIS IS THE ONE NUMBER IN THE DESIGN CHOSEN BY JUDGEMENT RATHER THAN
// MEASUREMENT. Dropping the projection dropped the only thing that used to
// catch a mis-keyed coordinate: a single wrong digit turns a parcel into a
// continent and the new maths would measure it without complaint. Every real
// shape in the CI fixtures -- everything but the handful added to sit either
// side of this line -- is under 0.05 degrees, so 10 leaves about two hundred
// times headroom over anything real while still catching a corner displaced
// to another continent. Raise it if a real file ever hits it. It replaces a
// 6-degree limit that existed because of the projection, so it is
// deliberately not 6.
export const MAX_EXTENT_DEGREES = 10.0;

// Above this many corners the self-intersection check is skipped and the
// shape is measured. The check is naive all-pairs, which is microseconds on
// the tens to low hundreds of corners a real ring has and quadratic beyond.
export const CROSSING_CHECK_CORNER_LIMIT = 512;

const SQUARE_METRES_PER_HECTARE = 10000.0;
const SQUARE_METRES_PER_SQUARE_KM = 1000000.0;

// Every reason a shape can be refused. Copied verbatim from kmz_points/
// geometry.py's REFUSALS -- these are the words an end user reads out of a
// spreadsheet banner, so the two implementations have to agree on them the
// same way they agree on a number. web/test/refusal.test.mjs compares the two
// lists, and a reason added on one side alone fails the build.
//
// Nothing here interpolates a caught exception's text. That is why the two
// earlier projection refusals are gone rather than reworded: they carried a
// Python library's wording into a banner an end user reads, and no
// implementation in another language could reproduce it.
export const NOT_ENOUGH_CORNERS = "needs at least 3 distinct corners, found {count}";
export const CORNER_OFF_THE_WORLD = "has a corner that is not a place on Earth";
export const TOO_LARGE = "is larger than any plot this tool is meant to measure";
export const OUTLINE_CROSSES_ITSELF = "its outline crosses itself";
// A hole that could not be measured used to be skipped in silence, which
// reported a plot with a courtyard as LARGER than it is. A wrong number that
// looks reasonable is the worst failure mode here, so the whole shape is now
// refused and the hole's own reason is carried through.
export const HOLE_NOT_MEASURABLE = "has a hole that cannot be measured: it {problem}";
export const HOLES_COVER_EVERYTHING = "its holes cover the whole shape, leaving no area";

export const REFUSALS = [
  NOT_ENOUGH_CORNERS,
  CORNER_OFF_THE_WORLD,
  TOO_LARGE,
  OUTLINE_CROSSES_ITSELF,
  HOLE_NOT_MEASURABLE,
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

/** An area and the distance round it, or the reason there is neither. */
export function measurement(squareMetres, problem = null, perimeterMetres = null) {
  return {
    squareMetres,
    problem,
    hectares: squareMetres === null ? null : squareMetres / SQUARE_METRES_PER_HECTARE,
    squareKilometres:
      squareMetres === null ? null : squareMetres / SQUARE_METRES_PER_SQUARE_KM,
    // Null for exactly the shapes squareMetres is null for.
    perimeterMetres,
  };
}

/**
 * Drop consecutive duplicates, including the repeated closing corner.
 *
 * KML writes rings closed, repeating the first coordinate last. Counting that
 * as a real corner adds a zero-length edge to every sum here.
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
 * An angle folded into (-180, 180].
 *
 * A loop rather than a remainder because the two languages disagree about the
 * sign of `%`: JavaScript keeps the sign of its left operand where Python
 * takes its right, so the obvious one-liner folds +357 correctly and leaves
 * -357 exactly where it was. Deltas here are at most a full turn, so this
 * runs at most twice.
 */
function folded(degrees) {
  let angle = degrees;
  while (angle > 180.0) angle -= 360.0;
  while (angle <= -180.0) angle += 360.0;
  return angle;
}

/**
 * Longitudes walked round the ring with the antimeridian jump taken out.
 *
 * Raw min and max would call any ring straddling 180 degrees 359 degrees wide
 * and refuse it, when what it actually spans is metres. Stepping by the
 * folded difference gives the span a person would measure, and it is also the
 * coordinate the crossing check needs -- two edges either side of the
 * antimeridian are neighbours on the ground and must be compared as such.
 */
function unwrappedLongitudes(ring) {
  const values = [ring[0].lon];
  for (let i = 1; i < ring.length; i += 1) {
    values.push(values[i - 1] + folded(ring[i].lon - ring[i - 1].lon));
  }
  return values;
}

/**
 * True when a corner is not a place on Earth.
 *
 * NaN and infinity get here from a coordinate the parser could not make sense
 * of, and they would otherwise travel silently through every formula below.
 * Number.isFinite is false for a string too, which is the same answer Python
 * gives: a coordinate that is not a number is not a place either.
 */
function offTheWorld(point) {
  return !(
    Number.isFinite(point.lat) &&
    Number.isFinite(point.lon) &&
    point.lat >= -90.0 &&
    point.lat <= 90.0 &&
    point.lon >= -180.0 &&
    point.lon <= 180.0
  );
}

/**
 * How far apart the largest and smallest of a list are.
 *
 * A loop rather than `Math.max(...values)`: nothing limits how many corners a
 * ring has now that the projection's own limits are gone, and spreading a
 * long array into a call overflows the stack rather than returning a number.
 */
function spread(values) {
  let smallest = values[0];
  let largest = values[0];
  for (const value of values) {
    if (value < smallest) smallest = value;
    if (value > largest) largest = value;
  }
  return largest - smallest;
}

/**
 * Why this ring cannot be measured, or null if it can.
 *
 * Everything a hole is checked for too. The crossing check is not here: it
 * applies to the outline alone -- see crossesItself.
 */
export function ringProblem(ring) {
  if (ring.length < 3) {
    return refuse(NOT_ENOUGH_CORNERS, { count: ring.length });
  }

  if (ring.some(offTheWorld)) return refuse(CORNER_OFF_THE_WORLD);

  const latitudes = ring.map((point) => point.lat);
  const longitudes = unwrappedLongitudes(ring);
  if (spread(latitudes) > MAX_EXTENT_DEGREES || spread(longitudes) > MAX_EXTENT_DEGREES) {
    return refuse(TOO_LARGE);
  }

  return null;
}

/**
 * Which way the path A to B to C turns: positive left, negative right.
 *
 * Only its sign is read, and the arithmetic is four multiplications of
 * doubles, so both languages compute the same bits.
 */
function orientation(ax, ay, bx, by, cx, cy) {
  return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
}

/** True when P, already known to be collinear with AB, lies inside it. */
function within(ax, ay, bx, by, px, py) {
  return (
    px >= Math.min(ax, bx) &&
    px <= Math.max(ax, bx) &&
    py >= Math.min(ay, by) &&
    py <= Math.max(ay, by)
  );
}

/**
 * True when segment first-second meets segment third-fourth.
 *
 * Touching counts. Two edges of a ring that are not neighbours have no
 * business sharing a point, and a figure-8 pinched at a single corner is as
 * unmeasurable as one whose lobes overlap.
 */
function segmentsCross(first, second, third, fourth) {
  const [ax, ay] = first;
  const [bx, by] = second;
  const [cx, cy] = third;
  const [dx, dy] = fourth;

  const d1 = orientation(cx, cy, dx, dy, ax, ay);
  const d2 = orientation(cx, cy, dx, dy, bx, by);
  const d3 = orientation(ax, ay, bx, by, cx, cy);
  const d4 = orientation(ax, ay, bx, by, dx, dy);

  // The ordinary case: each segment has the other's endpoints on opposite
  // sides of it.
  if (
    ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
    ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
  ) {
    return true;
  }

  // And the collinear ones, where an endpoint lies on the other segment.
  return (
    (d1 === 0 && within(cx, cy, dx, dy, ax, ay)) ||
    (d2 === 0 && within(cx, cy, dx, dy, bx, by)) ||
    (d3 === 0 && within(ax, ay, bx, by, cx, cy)) ||
    (d4 === 0 && within(ax, ay, bx, by, dx, dy))
  );
}

/**
 * True when the outline crosses or touches itself away from a corner.
 *
 * Naive all-pairs over non-adjacent edges, in degrees. A sweep line would be
 * asymptotically better and would need a tuned event queue and a comparison
 * budget -- constants that no cross-check could hold identical between the
 * two languages, in exchange for microseconds on rings this size.
 *
 * Only the outer ring is checked. Whether a hole sits inside the outline, or
 * whether two holes overlap, is deliberately out of scope: neither makes the
 * reported number meaningless the way a crossed outline does, and both cost a
 * containment test this file does not otherwise need.
 */
function crossesItself(ring) {
  const count = ring.length;
  if (count > CROSSING_CHECK_CORNER_LIMIT) return false;

  const longitudes = unwrappedLongitudes(ring);
  const corners = ring.map((point, index) => [longitudes[index], point.lat]);

  for (let i = 0; i < count; i += 1) {
    for (let j = i + 1; j < count; j += 1) {
      // Adjacent edges share an endpoint by construction, so they always
      // "touch". The gap is on the index, and count - 1 is the wraparound
      // pair -- the last edge ends where the first one starts.
      const gap = j - i;
      if (gap === 1 || gap === count - 1) continue;
      if (
        segmentsCross(
          corners[i],
          corners[(i + 1) % count],
          corners[j],
          corners[(j + 1) % count],
        )
      ) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Area of one ring on the authalic sphere, in square metres.
 *
 * Each corner's geodetic latitude becomes the authalic latitude -- the
 * latitude on a sphere of equal area -- and the spherical excess is summed
 * edge by edge in the TANGENT form. The naive excess formula loses all its
 * significant digits on a polygon a few hundred metres across, which is the
 * normal case here; this form keeps them.
 *
 * Absolute, because the signed sum is negative for one winding direction and
 * a shape's size does not depend on which way round it was drawn. Taking the
 * magnitude per ring is also what makes a hole's winding irrelevant.
 */
function ringArea(ring) {
  const count = ring.length;
  const halfTangents = ring.map((point) => Math.tan(authalicLatitude(point.lat) / 2));

  let total = 0.0;
  for (let i = 0; i < count; i += 1) {
    const j = (i + 1) % count;
    // Folding the step into (-pi, pi] is the whole antimeridian handling: a
    // ring crossing 180 degrees needs no special case.
    const delta = folded(ring[j].lon - ring[i].lon) * RADIANS_PER_DEGREE;
    const first = halfTangents[i];
    const second = halfTangents[j];
    total += 2 * Math.atan2(Math.tan(delta / 2) * (first + second), 1 + first * second);
  }

  return Math.abs(total) * AUTHALIC_RADIUS * AUTHALIC_RADIUS;
}

/**
 * Distance in metres along the ellipsoid between two points.
 *
 * Vincenty's inverse formula. It is iterative and famously fails to converge
 * for near-antipodal points; the extent ceiling means nothing here is more
 * than a few degrees across, so the loop is a handful of passes and the
 * iteration cap is a guard rather than a working limit.
 */
function vincenty(lat1, lon1, lat2, lon2) {
  const reduced1 = Math.atan((1 - FLATTENING) * Math.tan(lat1 * RADIANS_PER_DEGREE));
  const reduced2 = Math.atan((1 - FLATTENING) * Math.tan(lat2 * RADIANS_PER_DEGREE));
  const sinU1 = Math.sin(reduced1);
  const cosU1 = Math.cos(reduced1);
  const sinU2 = Math.sin(reduced2);
  const cosU2 = Math.cos(reduced2);

  const difference = folded(lon2 - lon1) * RADIANS_PER_DEGREE;
  let angle = difference;

  let sinSigma = 0.0;
  let cosSigma = 1.0;
  let sigma = 0.0;
  let cosSqAlpha = 1.0;
  let cos2SigmaM = 0.0;

  for (let iteration = 0; iteration < VINCENTY_ITERATIONS; iteration += 1) {
    const sinAngle = Math.sin(angle);
    const cosAngle = Math.cos(angle);
    // Written out rather than through hypot: the two languages' hypot are
    // separately implemented, and this is four multiplications and a square
    // root that both compute to the same bits.
    const across = cosU2 * sinAngle;
    const along = cosU1 * sinU2 - sinU1 * cosU2 * cosAngle;
    sinSigma = Math.sqrt(across * across + along * along);
    // Coincident corners. A ring can hold two of them, and 0/0 below is a
    // ZeroDivisionError in Python and a NaN in JavaScript -- neither is a
    // distance, and both would poison the sum.
    if (sinSigma === 0.0) return 0.0;
    cosSigma = sinU1 * sinU2 + cosU1 * cosU2 * cosAngle;
    sigma = Math.atan2(sinSigma, cosSigma);
    const sinAlpha = (cosU1 * cosU2 * sinAngle) / sinSigma;
    cosSqAlpha = 1 - sinAlpha * sinAlpha;
    // Zero along the equator, where there is no vertex to measure from.
    cos2SigmaM = cosSqAlpha ? cosSigma - (2 * sinU1 * sinU2) / cosSqAlpha : 0.0;
    const correction =
      (FLATTENING / 16) * cosSqAlpha * (4 + FLATTENING * (4 - 3 * cosSqAlpha));
    const previous = angle;
    angle =
      difference +
      (1 - correction) *
        FLATTENING *
        sinAlpha *
        (sigma +
          correction *
            sinSigma *
            (cos2SigmaM + correction * cosSigma * (-1 + 2 * cos2SigmaM * cos2SigmaM)));
    if (Math.abs(angle - previous) < VINCENTY_TOLERANCE) break;
  }

  const uSquared =
    (cosSqAlpha * (SEMI_MAJOR * SEMI_MAJOR - SEMI_MINOR * SEMI_MINOR)) /
    (SEMI_MINOR * SEMI_MINOR);
  const termA =
    1 +
    (uSquared / 16384) * (4096 + uSquared * (-768 + uSquared * (320 - 175 * uSquared)));
  const termB =
    (uSquared / 1024) * (256 + uSquared * (-128 + uSquared * (74 - 47 * uSquared)));
  const deltaSigma =
    termB *
    sinSigma *
    (cos2SigmaM +
      (termB / 4) *
        (cosSigma * (-1 + 2 * cos2SigmaM * cos2SigmaM) -
          (termB / 6) *
            cos2SigmaM *
            (-3 + 4 * sinSigma * sinSigma) *
            (-3 + 4 * cos2SigmaM * cos2SigmaM)));
  return SEMI_MINOR * termA * (sigma - deltaSigma);
}

/**
 * The distance round one ring, edge by edge along the ellipsoid.
 *
 * The outline only. A hole's boundary is a second fence rather than part of
 * the first, and the banner names one shape's outline.
 */
function ringPerimeter(ring) {
  let total = 0.0;
  for (let i = 0; i < ring.length; i += 1) {
    const j = (i + 1) % ring.length;
    total += vincenty(ring[i].lat, ring[i].lon, ring[j].lat, ring[j].lon);
  }
  return total;
}

/**
 * Area of a polygon on the ellipsoid, holes subtracted, and its perimeter.
 *
 * Each ring is measured by its own spherical excess and subtracted by
 * magnitude, so no ring's winding direction changes the answer and no two
 * rings are measured against different grids the way a forced projection made
 * possible.
 */
export function polygonArea(outer, holes = []) {
  const ring = distinctCorners(outer);

  const problem = ringProblem(ring);
  if (problem !== null) return measurement(null, problem);

  if (crossesItself(ring)) {
    // Both the shoelace and the excess return a signed sum for a crossed
    // ring, in which the lobes partly cancel. The number that would come out
    // is the area of nothing at all.
    return measurement(null, refuse(OUTLINE_CROSSES_ITSELF));
  }

  let total = ringArea(ring);
  for (const hole of holes) {
    const holeRing = distinctCorners(hole);
    const holeProblem = ringProblem(holeRing);
    if (holeProblem !== null) {
      return measurement(null, refuse(HOLE_NOT_MEASURABLE, { problem: holeProblem }));
    }
    total -= ringArea(holeRing);
  }

  if (total <= 0) {
    return measurement(null, refuse(HOLES_COVER_EVERYTHING));
  }

  return measurement(total, null, ringPerimeter(ring));
}

/** An area paired with its size, ready to be written out. */
export function measure(area) {
  return { area, measurement: polygonArea(area.outer, area.holes || []) };
}
