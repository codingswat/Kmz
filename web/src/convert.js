/**
 * Coordinate conversions.
 *
 * A port of kmz_points/convert.py. Pure functions, no I/O. Every function is
 * total: out-of-range input yields null rather than throwing, so one bad
 * point can never abort a batch.
 *
 * UTM and MGRS are implemented here rather than pulled from a library
 * because the Python side gets MGRS from a compiled C library, which has no
 * browser equivalent. The formulas are the standard ones and the results are
 * checked against the Python implementation, coordinate by coordinate.
 *
 * Rounding carries. Formatting 34.99999999 by truncating degrees and
 * rounding minutes independently gives "34 deg 60.0000'", which is not a
 * coordinate, so each formatter rounds the smallest unit first and
 * propagates any overflow upward.
 */

// WGS 84.
const A = 6378137.0;
const F = 1 / 298.257223563;
const E2 = F * (2 - F);
const E_PRIME2 = E2 / (1 - E2);
const K0 = 0.9996;

const UTM_MIN_LAT = -80.0;
const UTM_MAX_LAT = 84.0;

const RAD = Math.PI / 180;

/** The latitude band letter, C through X with I and O skipped. */
export function latitudeBand(lat) {
  if (lat < UTM_MIN_LAT || lat > UTM_MAX_LAT) return null;
  const letters = "CDEFGHJKLMNPQRSTUVWXX";
  return letters[Math.floor((lat + 80) / 8)];
}

/** An angle in radians folded into [-pi, pi). Mirrors Python's utm.mod_angle. */
function modAngle(value) {
  return ((value + Math.PI) % (2 * Math.PI)) - Math.PI;
}

function zoneNumber(lat, lon) {
  // Fold into [-180, 180) before anything else, exactly as Python's utm does.
  // Without this a longitude of exactly 180 produced zone 61, which is not a
  // zone -- there are 60 -- and the antimeridian is a real place to stand.
  lon = ((((lon % 360) + 540) % 360)) - 180;

  // Two exceptions to the regular 6-degree grid, both long-standing.
  if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) return 32;
  // 84 inclusive: the band runs up to and including its top edge, and a
  // latitude of exactly 84 was taking the ordinary grid instead of Svalbard's.
  if (lat >= 72 && lat <= 84 && lon >= 0) {
    if (lon < 9) return 31;
    if (lon < 21) return 33;
    if (lon < 33) return 35;
    if (lon < 42) return 37;
  }
  return Math.floor((lon + 180) / 6) + 1;
}

function inRange(lat, lon) {
  return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

/**
 * Project to UTM. Returns {zone, band, easting, northing} or null where UTM
 * is undefined. `forceZone` keeps a shape's corners on one grid.
 */
export function toUtm(lat, lon, forceZone = null) {
  if (!inRange(lat, lon)) return null;
  if (lat < UTM_MIN_LAT || lat > UTM_MAX_LAT) return null;

  const zone = forceZone || zoneNumber(lat, lon);
  const band = latitudeBand(lat);

  const latRad = lat * RAD;
  const lonRad = lon * RAD;
  const centralMeridian = ((zone - 1) * 6 - 180 + 3) * RAD;

  const n = A / Math.sqrt(1 - E2 * Math.sin(latRad) ** 2);
  const t = Math.tan(latRad) ** 2;
  const c = E_PRIME2 * Math.cos(latRad) ** 2;
  // Wrapped into [-pi, pi], as Python's utm.mod_angle does. Without it a
  // point just the far side of the antimeridian sits 357 degrees from its
  // own zone's central meridian instead of 3, and the series expansion below
  // -- which assumes a small angle -- returns billions of metres.
  const a = Math.cos(latRad) * modAngle(lonRad - centralMeridian);

  const m =
    A *
    ((1 - E2 / 4 - (3 * E2 ** 2) / 64 - (5 * E2 ** 3) / 256) * latRad -
      ((3 * E2) / 8 + (3 * E2 ** 2) / 32 + (45 * E2 ** 3) / 1024) *
        Math.sin(2 * latRad) +
      ((15 * E2 ** 2) / 256 + (45 * E2 ** 3) / 1024) * Math.sin(4 * latRad) -
      ((35 * E2 ** 3) / 3072) * Math.sin(6 * latRad));

  const easting =
    K0 *
      n *
      (a +
        ((1 - t + c) * a ** 3) / 6 +
        ((5 - 18 * t + t ** 2 + 72 * c - 58 * E_PRIME2) * a ** 5) / 120) +
    500000.0;

  let northing =
    K0 *
    (m +
      n *
        Math.tan(latRad) *
        (a ** 2 / 2 +
          ((5 - t + 9 * c + 4 * c ** 2) * a ** 4) / 24 +
          ((61 - 58 * t + t ** 2 + 600 * c - 330 * E_PRIME2) * a ** 6) / 720));

  if (lat < 0) northing += 10000000.0; // false northing in the south

  return { zone, band, easting, northing };
}

/** ``37S 419595 E 3825474 N`` */
export function utmLabel(point) {
  if (!point) return "";
  return `${point.zone}${point.band} ${Math.round(point.easting)} E ${Math.round(point.northing)} N`;
}

// MGRS 100km square lettering, the AA scheme WGS 84 uses. I and O are absent
// throughout: they are too easily read as 1 and 0.
const COLUMN_LETTERS = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"];
const ROW_LETTERS = ["ABCDEFGHJKLMNPQRSTUV", "FGHJKLMNPQRSTUVABCDE"];

/**
 * An MGRS grid reference at 1 m precision, e.g. ``37SDU1959425474``, or null
 * where it cannot be computed.
 */
export function toMgrs(lat, lon) {
  const point = toUtm(lat, lon);
  if (!point) return null;

  const { zone, band, easting, northing } = point;

  const columnSet = (zone - 1) % 3;
  const columnIndex = Math.floor(easting / 100000) - 1;
  if (columnIndex < 0 || columnIndex > 7) return null;
  const columnLetter = COLUMN_LETTERS[columnSet][columnIndex];

  const rowSet = (zone - 1) % 2;
  const rowIndex = Math.floor(northing / 100000) % 20;
  const rowLetter = ROW_LETTERS[rowSet][rowIndex];

  const eastPart = String(Math.floor(easting % 100000)).padStart(5, "0");
  const northPart = String(Math.floor(northing % 100000)).padStart(5, "0");

  // Zone is zero-padded to two digits, as MGRS references conventionally
  // are: "02CNS...", not "2CNS...".
  const zonePart = String(zone).padStart(2, "0");
  return `${zonePart}${band}${columnLetter}${rowLetter}${eastPart}${northPart}`;
}

// Reused rather than allocated per call: this runs once per number in every
// area banner, and the buffer is read back before anything else can touch it.
const BITS = new DataView(new ArrayBuffer(8));

/**
 * A double's exact value as `mantissa * 2 ** exponent`, both integers.
 *
 * Every finite double is exactly a dyadic rational, so this loses nothing --
 * which is the point. It is what lets exactFixed round the number that is
 * actually stored rather than the shortest decimal that happens to print as
 * it.
 */
function dyadic(value) {
  BITS.setFloat64(0, value);
  const bits = BITS.getBigUint64(0);
  const biased = Number((bits >> 52n) & 0x7ffn);
  const fraction = bits & 0xfffffffffffffn;
  // Subnormals have no implicit leading 1 and a fixed exponent.
  if (biased === 0) return { mantissa: fraction, exponent: -1074 };
  return { mantissa: fraction | (1n << 52n), exponent: biased - 1075 };
}

/**
 * `value` to `places` decimals, exactly as Python's ``format(x, f".{p}f")``.
 *
 * Neither of the obvious JavaScript answers agrees with Python, and both
 * disagreements produce a digit an end user reads:
 *
 *   - `toLocaleString` rounds the SHORTEST DECIMAL that prints as the double,
 *     not the double. 548.3335 is stored as 548.33349999…, which Python
 *     renders as "548.333"; toLocaleString renders "548.334".
 *   - `toFixed` does round the stored value, but breaks an exact tie AWAY
 *     FROM ZERO where Python breaks it TO EVEN. 0.0625 is exactly 1/16, so
 *     three decimals is a genuine tie: Python gives "0.062", toFixed "0.063".
 *
 * Measured over 695,628 value/precision pairs against Python: toLocaleString
 * disagreed on 6,025, toFixed on 1,980, this on none.
 *
 * BigInt throughout, because the arithmetic that decides the last digit is
 * exactly the arithmetic a double cannot do.
 */
export function exactFixed(value, places) {
  // Python prints these as words, and nothing here may throw.
  if (Number.isNaN(value)) return "nan";
  if (!Number.isFinite(value)) return value > 0 ? "inf" : "-inf";

  // Object.is, because -0.0 is negative to Python and `-0 < 0` is false.
  const negative = value < 0 || Object.is(value, -0);
  const { mantissa, exponent } = dyadic(Math.abs(value));

  const scaled = mantissa * 10n ** BigInt(places);
  let digits;
  if (exponent >= 0) {
    digits = scaled << BigInt(exponent); // an integer already; nothing to round
  } else {
    const divisor = 1n << BigInt(-exponent);
    const whole = scaled / divisor;
    const twiceRemainder = (scaled % divisor) * 2n;
    const roundUp =
      twiceRemainder > divisor ||
      // The tie: to even, which is what Python does and toFixed does not.
      (twiceRemainder === divisor && (whole & 1n) === 1n);
    digits = roundUp ? whole + 1n : whole;
  }

  // padStart guarantees a digit before the point for values under 1.
  const text = digits.toString().padStart(places + 1, "0");
  const point = text.length - places;
  const sign = negative ? "-" : "";
  if (!places) return sign + text;
  return `${sign}${text.slice(0, point)}.${text.slice(point)}`;
}

/** Signed decimal degrees to six places: ``34.567890``. */
export function formatDd(value) {
  const rounded = Math.round(value * 1e6) / 1e6;
  // Collapse -0 so a tiny negative does not render as "-0.000000".
  return (rounded === 0 ? 0 : rounded).toFixed(6);
}

function hemisphere(value, axis) {
  if (axis === "lat") return value >= 0 ? "N" : "S";
  return value >= 0 ? "E" : "W";
}

/**
 * Whole degrees, whole minutes and seconds, all as MAGNITUDES.
 *
 * The sign is deliberately not carried: degrees cannot express it for a value
 * between -1 and 0, since a latitude of -0.180653 is south but its
 * whole-degree part is 0, and 0 has no sign. Callers pair these with the
 * signed decimal, which is what tells you the hemisphere.
 */
export function dmsParts(value) {
  const magnitude = Math.abs(value);
  let degrees = Math.floor(magnitude);
  const totalMinutes = (magnitude - degrees) * 60;
  let minutes = Math.floor(totalMinutes);
  let seconds = Math.round((totalMinutes - minutes) * 60 * 100) / 100;

  if (seconds >= 60) {
    seconds -= 60;
    minutes += 1;
  }
  if (minutes >= 60) {
    minutes -= 60;
    degrees += 1;
  }
  return { degrees, minutes, seconds };
}

/** ``34° 34.0734' N`` */
export function formatDdm(value, axis) {
  const side = hemisphere(value, axis);
  const magnitude = Math.abs(value);
  let degrees = Math.floor(magnitude);
  let minutes = Math.round((magnitude - degrees) * 60 * 1e4) / 1e4;
  if (minutes >= 60) {
    minutes -= 60;
    degrees += 1;
  }
  return `${degrees}° ${minutes.toFixed(4)}' ${side}`;
}

/** ``34° 34' 4.40" N`` */
export function formatDms(value, axis) {
  const side = hemisphere(value, axis);
  const { degrees, minutes, seconds } = dmsParts(value);
  return `${degrees}° ${minutes}' ${seconds.toFixed(2)}" ${side}`;
}
