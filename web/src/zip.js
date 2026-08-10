/**
 * A minimal ZIP writer.
 *
 * An xlsx is a zip of XML files, so writing one needs a zip writer. Entries
 * are stored uncompressed: it costs file size on a format that is mostly
 * short XML anyway, and it buys having no dependency and no compression code
 * to be wrong about. Excel, openpyxl and every other reader accept stored
 * entries -- compression is optional in the format.
 *
 * Runs unchanged in a browser and in Node: no DOM, no filesystem, bytes in
 * and bytes out.
 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let value = i;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[i] = value >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** Bytes for a string, as UTF-8. */
export function utf8(text) {
  return new TextEncoder().encode(text);
}

class ByteWriter {
  constructor() {
    this.parts = [];
    this.length = 0;
  }

  bytes(chunk) {
    this.parts.push(chunk);
    this.length += chunk.length;
  }

  u16(value) {
    this.bytes(new Uint8Array([value & 0xff, (value >>> 8) & 0xff]));
  }

  u32(value) {
    this.bytes(
      new Uint8Array([
        value & 0xff,
        (value >>> 8) & 0xff,
        (value >>> 16) & 0xff,
        (value >>> 24) & 0xff,
      ]),
    );
  }

  concat() {
    const out = new Uint8Array(this.length);
    let at = 0;
    for (const part of this.parts) {
      out.set(part, at);
      at += part.length;
    }
    return out;
  }
}

/**
 * Build a zip from `{name -> string | Uint8Array}`.
 *
 * Timestamps are fixed rather than taken from the clock, so the same input
 * always produces byte-identical output. That is what lets a test compare two
 * runs, and it keeps the file from carrying the time it was made.
 */
export function zip(files) {
  const entries = [];
  const body = new ByteWriter();

  for (const [name, content] of Object.entries(files)) {
    const data = typeof content === "string" ? utf8(content) : content;
    const nameBytes = utf8(name);
    const checksum = crc32(data);
    const offset = body.length;

    body.u32(0x04034b50); // local file header
    body.u16(20); // version needed
    body.u16(0);
    body.u16(0); // stored, not deflated
    body.u16(0); // time
    body.u16(0x21); // date: 1980-01-01, fixed for reproducibility
    body.u32(checksum);
    body.u32(data.length);
    body.u32(data.length);
    body.u16(nameBytes.length);
    body.u16(0);
    body.bytes(nameBytes);
    body.bytes(data);

    entries.push({ nameBytes, checksum, size: data.length, offset });
  }

  const directory = new ByteWriter();
  for (const entry of entries) {
    directory.u32(0x02014b50); // central directory header
    directory.u16(20); // version made by
    directory.u16(20); // version needed
    directory.u16(0);
    directory.u16(0);
    directory.u16(0);
    directory.u16(0x21);
    directory.u32(entry.checksum);
    directory.u32(entry.size);
    directory.u32(entry.size);
    directory.u16(entry.nameBytes.length);
    directory.u16(0);
    directory.u16(0);
    directory.u16(0);
    directory.u16(0);
    directory.u32(0);
    directory.u32(entry.offset);
    directory.bytes(entry.nameBytes);
  }

  const end = new ByteWriter();
  end.u32(0x06054b50); // end of central directory
  end.u16(0);
  end.u16(0);
  end.u16(entries.length);
  end.u16(entries.length);
  end.u32(directory.length);
  end.u32(body.length);
  end.u16(0);

  const out = new ByteWriter();
  out.bytes(body.concat());
  out.bytes(directory.concat());
  out.bytes(end.concat());
  return out.concat();
}
