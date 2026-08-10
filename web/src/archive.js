/**
 * Getting KML bytes out of a .kml or .kmz.
 *
 * A port of kmz_points/archive.py. A KMZ is a zip archive; the convention is
 * a doc.kml at the root, but exporters vary, so any .kml entry will do as a
 * fallback.
 */

import { listEntries, readEntry, ZipError } from "./unzip.js";

export class ArchiveError extends Error {}

const ALLOWED = [".kml", ".kmz"];

function suffixOf(name) {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/** The basename, with any directory component discarded. */
export function baseName(name) {
  return name.split(/[\\/]/).pop() || name;
}

async function readFromKmz(bytes, displayName) {
  let entries;
  try {
    entries = listEntries(bytes);
  } catch (error) {
    throw new ArchiveError(`${displayName}: not a readable KMZ archive`);
  }

  const candidates = entries.filter((entry) => suffixOf(entry.name) === ".kml");
  if (!candidates.length) {
    throw new ArchiveError(`${displayName}: archive contains no .kml file`);
  }

  // Prefer doc.kml at any depth, else the first .kml present.
  const chosen =
    candidates.find((entry) => baseName(entry.name).toLowerCase() === "doc.kml") ||
    candidates[0];

  try {
    return await readEntry(bytes, chosen);
  } catch (error) {
    if (error instanceof ZipError) {
      throw new ArchiveError(`${displayName}: ${error.message}`);
    }
    throw new ArchiveError(`${displayName}: not a readable KMZ archive`);
  }
}

/**
 * Return the KML document bytes for a .kml or .kmz file's contents.
 *
 * `name` is used only for messages -- nothing is read from disk, and no path
 * from it is ever followed.
 */
export async function readKmlBytes(bytes, name) {
  const displayName = baseName(name);
  const suffix = suffixOf(displayName);

  if (!ALLOWED.includes(suffix)) {
    throw new ArchiveError(`${displayName}: not a .kml or .kmz file`);
  }
  if (suffix === ".kmz") return readFromKmz(bytes, displayName);
  return bytes;
}
