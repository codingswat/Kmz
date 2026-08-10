/**
 * Orchestration: files in, one workbook out.
 *
 * A port of kmz_points/pipeline.py, and it keeps that module's central
 * promise: nothing here throws on bad input. A batch containing a corrupt
 * file, a KMZ with no KML inside, or a document with nothing in it still
 * exports everything it could read and reports the rest as warnings.
 */

import { ArchiveError, baseName, readKmlBytes } from "./archive.js";
import { measure } from "./geometry.js";
import { parseDocument } from "./kml.js";
import { buildTableRows } from "./table.js";
import { buildBatchWorkbook, outputFilename } from "./workbook.js";

/**
 * Read and parse one file. Never throws.
 *
 * Takes bytes and a name rather than a path: in a browser there is no
 * filesystem, and the name is only ever used for messages.
 */
export async function loadFile(bytes, name) {
  const displayName = baseName(name);

  let kml;
  try {
    kml = await readKmlBytes(bytes, displayName);
  } catch (error) {
    const message =
      error instanceof ArchiveError
        ? error.message
        : `${displayName}: ${error.message}`;
    return { name: displayName, points: [], areas: [], skipped: 0, warnings: [], error: message };
  }

  const text = new TextDecoder().decode(kml);
  const result = parseDocument(text, displayName);
  return {
    name: displayName,
    points: result.points,
    areas: result.areas,
    skipped: result.skipped,
    warnings: result.warnings,
    error: null,
  };
}

/**
 * Reduce a batch to its points, its measured areas and its summary.
 *
 * Areas are measured here rather than in the writer, so the spreadsheet layer
 * never imports the geometry maths.
 */
export function collect(loaded) {
  const summary = {
    filesRead: 0,
    filesFailed: 0,
    pointsExtracted: 0,
    areasExtracted: 0,
    featuresSkipped: 0,
    warnings: [],
  };
  const points = [];
  const areas = [];

  for (const item of loaded) {
    if (!item.error) {
      summary.filesRead += 1;
      summary.featuresSkipped += item.skipped;
      points.push(...item.points);
      areas.push(...item.areas.map(measure));
    } else {
      summary.filesFailed += 1;
      summary.warnings.push(item.error);
    }
    summary.warnings.push(...item.warnings);
  }

  summary.pointsExtracted = points.length;
  summary.areasExtracted = areas.length;

  for (const measured of areas) {
    if (measured.measurement.squareMetres === null) {
      summary.warnings.push(
        `${measured.area.sourceFile}: area ` +
          `${measured.area.name || "<unnamed>"} not measured ` +
          `(${measured.measurement.problem})`,
      );
    }
  }

  return { points, areas, summary };
}

/** ``as_text``'s counterpart: the summary as the lines a person reads. */
export function summaryText(summary) {
  const lines = [
    `${summary.filesRead} file(s) read`,
    `${summary.pointsExtracted} point(s) extracted`,
    `${summary.areasExtracted} area(s) extracted`,
    `${summary.featuresSkipped} non-point feature(s) skipped`,
  ];
  if (summary.filesFailed) lines.push(`${summary.filesFailed} file(s) failed`);
  return lines.join("\n");
}

/**
 * Convert a batch of files.
 *
 * Returns `{summary, workbook, filename}`; `workbook` is null when the batch
 * yielded neither points nor areas, which is the same rule the service uses
 * to decide between a download and a message.
 */
export async function convert(files, when = new Date()) {
  const loaded = [];
  for (const file of files) {
    loaded.push(await loadFile(file.bytes, file.name));
  }

  const { points, areas, summary } = collect(loaded);

  if (!points.length && !areas.length) {
    summary.warnings.push("No points found; nothing was written.");
    return { summary, workbook: null, filename: null };
  }

  const workbook = buildBatchWorkbook({
    rows: buildTableRows(points),
    areas,
    issues: summary.warnings,
  });

  return { summary, workbook, filename: outputFilename(when) };
}
