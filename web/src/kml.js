/**
 * Extracting points and areas from a KML document.
 *
 * A port of kmz_points/kml_parser.py. Namespace handling is deliberately
 * blunt: elements are matched on their local name, so KML 2.2, the legacy
 * Google Earth namespaces and namespace-less files all take the same path.
 * Matching on a fixed namespace URI is the usual reason a parser silently
 * returns zero points.
 *
 * This is the only module that needs a DOM, which is why its cross-check
 * against Python runs in a browser rather than in Node.
 *
 * Never throws: unreadable documents and malformed coordinates are reported
 * as warnings so one bad file cannot abort a batch.
 */

// Counted but not extracted. LinearRing is absent on purpose -- it lives
// inside Polygon and would count every shape twice -- and Polygon is absent
// because its areas are extracted now.
const NON_POINT_GEOMETRY = new Set(["LineString", "Model", "Track"]);

function localName(element) {
  return element.localName || element.nodeName.replace(/^.*:/, "");
}

function descendants(root, name) {
  const found = [];
  const walk = (element) => {
    for (const child of element.children) {
      if (localName(child) === name) found.push(child);
      walk(child);
    }
  };
  walk(root);
  return found;
}

function childNamed(element, name) {
  for (const child of element.children) {
    if (localName(child) === name) return child;
  }
  return null;
}

function textOf(element) {
  return element ? (element.textContent || "").trim() : "";
}

/** Reduce CDATA/HTML description markup to a single line of plain text. */
export function plainText(raw) {
  if (!raw || !raw.trim()) return "";
  if (!raw.includes("<")) return raw.split(/\s+/).join(" ");

  const holder = document.createElement("div");
  holder.innerHTML = raw;
  // Give breaks and block elements a separator, or words either side of them
  // run together once the tags are gone.
  for (const element of holder.querySelectorAll("br, p, div, li, tr")) {
    element.insertAdjacentText("afterend", "\n");
  }
  return (holder.textContent || "").split(/\s+/).filter(Boolean).join(" ");
}

/**
 * Parse a KML `lon,lat[,alt]` triple. Returns null if unusable.
 */
export function parseCoordinate(entry) {
  const parts = entry.split(",");
  if (parts.length < 2) return null;
  const lon = Number(parts[0]);
  const lat = Number(parts[1]);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  const alt =
    parts.length > 2 && parts[2].trim() !== "" ? Number(parts[2]) : null;
  return { lon, lat, alt: Number.isFinite(alt) ? alt : null };
}

/**
 * Parse a whitespace-separated run of triples.
 *
 * Unusable entries are dropped rather than failing the ring: one bad corner
 * should not lose the whole shape.
 */
export function parseCoordinateList(text) {
  if (!text || !text.trim()) return [];
  return text
    .trim()
    .split(/\s+/)
    .map(parseCoordinate)
    .filter((corner) => corner !== null);
}

function ringCorners(boundary, name, sourceFile) {
  const corners = [];
  for (const ring of descendants(boundary, "LinearRing")) {
    const coordinates = childNamed(ring, "coordinates");
    for (const corner of parseCoordinateList(textOf(coordinates))) {
      corners.push({
        name,
        description: "",
        lon: corner.lon,
        lat: corner.lat,
        alt: corner.alt,
        sourceFile,
      });
    }
  }
  return corners;
}

function parsePolygon(polygon, name, description, sourceFile) {
  const outer = [];
  for (const boundary of descendants(polygon, "outerBoundaryIs")) {
    outer.push(...ringCorners(boundary, name, sourceFile));
  }
  if (!outer.length) return null;

  const holes = [];
  for (const boundary of descendants(polygon, "innerBoundaryIs")) {
    const corners = ringCorners(boundary, name, sourceFile);
    if (corners.length) holes.push(corners);
  }

  return { name, description, outer, holes, sourceFile };
}

/**
 * Extract every Placemark Point and Polygon in a KML document.
 *
 * Returns `{points, areas, skipped, warnings}`.
 */
export function parseDocument(text, sourceFile) {
  const result = { points: [], areas: [], skipped: 0, warnings: [] };

  const parsed = new DOMParser().parseFromString(text, "application/xml");
  const failure = parsed.querySelector("parsererror");
  if (failure || !parsed.documentElement) {
    result.warnings.push("file is not valid XML and could not be read");
    return result;
  }

  for (const placemark of descendants(parsed.documentElement, "Placemark")) {
    const name = textOf(childNamed(placemark, "name"));
    const descriptionElement = childNamed(placemark, "description");
    const description = plainText(
      descriptionElement ? descriptionElement.textContent : "",
    );

    const walk = (element) => {
      for (const child of element.children) {
        if (NON_POINT_GEOMETRY.has(localName(child))) result.skipped += 1;
        walk(child);
      }
    };
    walk(placemark);
    if (NON_POINT_GEOMETRY.has(localName(placemark))) result.skipped += 1;

    for (const pointElement of descendants(placemark, "Point")) {
      const coordinates = childNamed(pointElement, "coordinates");
      const raw = textOf(coordinates);
      const first = raw.split(/\s+/)[0] || "";
      const corner = parseCoordinate(first);
      if (!corner) {
        result.warnings.push(
          `${sourceFile}: skipped ${name || "<unnamed>"} (bad coordinates)`,
        );
        continue;
      }
      result.points.push({
        name,
        description,
        lon: corner.lon,
        lat: corner.lat,
        alt: corner.alt,
        sourceFile,
      });
    }

    for (const polygon of descendants(placemark, "Polygon")) {
      const area = parsePolygon(polygon, name, description, sourceFile);
      if (!area) {
        result.warnings.push(
          `${sourceFile}: skipped area ${name || "<unnamed>"} (no usable outline)`,
        );
        continue;
      }
      result.areas.push(area);
    }
  }

  return result;
}
