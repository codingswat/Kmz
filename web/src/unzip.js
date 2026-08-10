/**
 * Reading a ZIP, which is what a KMZ is.
 *
 * Uses DecompressionStream("deflate-raw"), which browsers and Node both
 * provide, so there is no dependency and no inflate implementation of mine to
 * be wrong about.
 *
 * The size cap is the same defence the Python side carries: a small archive
 * can declare an entry that expands to hundreds of megabytes. Here it matters
 * differently -- a browser tab has less memory to lose than a server -- but
 * the fix is the same. The declared size is checked before decompressing, and
 * the result is checked again after, because nothing forces an archive to
 * describe itself truthfully.
 */

const SIGNATURE_END_OF_DIRECTORY = 0x06054b50;
const SIGNATURE_DIRECTORY_ENTRY = 0x02014b50;

const STORED = 0;
const DEFLATED = 8;

/** No legitimate KML document approaches this. */
export const MAX_ENTRY_BYTES = 200 * 1024 * 1024;

export class ZipError extends Error {}

function view(bytes) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

function findEndOfDirectory(bytes) {
  const data = view(bytes);
  // The trailer is at the very end unless there is a comment, which is
  // capped at 64 KB by the format.
  const earliest = Math.max(0, bytes.length - 22 - 0xffff);
  for (let at = bytes.length - 22; at >= earliest; at -= 1) {
    if (data.getUint32(at, true) === SIGNATURE_END_OF_DIRECTORY) return at;
  }
  throw new ZipError("not a readable KMZ archive");
}

/**
 * List the entries without decompressing any of them.
 *
 * Returns `[{name, offset, compressedSize, size, method}]`.
 */
export function listEntries(bytes) {
  const data = view(bytes);
  const end = findEndOfDirectory(bytes);
  const count = data.getUint16(end + 10, true);
  let at = data.getUint32(end + 16, true);

  const entries = [];
  for (let i = 0; i < count; i += 1) {
    if (data.getUint32(at, true) !== SIGNATURE_DIRECTORY_ENTRY) {
      throw new ZipError("not a readable KMZ archive");
    }
    const method = data.getUint16(at + 10, true);
    const compressedSize = data.getUint32(at + 20, true);
    const size = data.getUint32(at + 24, true);
    const nameLength = data.getUint16(at + 28, true);
    const extraLength = data.getUint16(at + 30, true);
    const commentLength = data.getUint16(at + 32, true);
    const offset = data.getUint32(at + 42, true);
    const name = new TextDecoder().decode(
      bytes.subarray(at + 46, at + 46 + nameLength),
    );

    entries.push({ name, offset, compressedSize, size, method });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function inflateRaw(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(
    new DecompressionStream("deflate-raw"),
  );
  const chunks = [];
  let total = 0;
  const reader = stream.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    total += value.length;
    // Checked while decompressing, not after: an entry that under-declares
    // its size would otherwise be fully expanded before anyone objected.
    if (total > MAX_ENTRY_BYTES) {
      await reader.cancel();
      throw new ZipError(
        `an entry expands past the ${MAX_ENTRY_BYTES / (1024 * 1024)} MB limit`,
      );
    }
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    out.set(chunk, at);
    at += chunk.length;
  }
  return out;
}

/** Decompress one entry, refusing anything that expands past the cap. */
export async function readEntry(bytes, entry) {
  if (entry.size > MAX_ENTRY_BYTES) {
    throw new ZipError(
      `${entry.name} would expand to about ` +
        `${Math.ceil(entry.size / (1024 * 1024))} MB, over the ` +
        `${MAX_ENTRY_BYTES / (1024 * 1024)} MB limit`,
    );
  }

  const data = view(bytes);
  // The local header repeats the name and extra fields, at their own lengths
  // -- the central directory's lengths do not apply here.
  const nameLength = data.getUint16(entry.offset + 26, true);
  const extraLength = data.getUint16(entry.offset + 28, true);
  const start = entry.offset + 30 + nameLength + extraLength;
  const compressed = bytes.subarray(start, start + entry.compressedSize);

  if (entry.method === STORED) return compressed.slice();
  if (entry.method === DEFLATED) return inflateRaw(compressed);
  throw new ZipError(`${entry.name}: unsupported compression`);
}
