import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import sharp from "sharp";

const icon = readFileSync(new URL("../../app/favicon.ico", import.meta.url));
const source = readFileSync(new URL("../../public/pwa-icon-192.png", import.meta.url));
const offset = icon.readUInt32LE(18);
const length = icon.readUInt32LE(14);
const payload = icon.subarray(offset, offset + length);

test("the automatic favicon contains one correctly bounded 32-bit PNG frame", () => {
  assert.equal(icon.readUInt16LE(0), 0);
  assert.equal(icon.readUInt16LE(2), 1);
  assert.equal(icon.readUInt16LE(4), 1);
  assert.equal(offset, 22);
  assert.equal(icon.length, offset + length);
  assert.equal(icon[6] || 256, source.readUInt32BE(16));
  assert.equal(icon[7] || 256, source.readUInt32BE(20));
  assert.equal(icon[8], 0); // True-color PNG, not an indexed icon palette.
  assert.equal(icon.readUInt16LE(10), 1);
  assert.equal(icon.readUInt16LE(12), 32);
  assert.deepEqual(payload.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  assert.equal(payload[24], 8); // Eight bits per channel.
  assert.equal(payload[25], 6); // RGBA is required by the Next/Turbopack ICO decoder.
});

test("the embedded RGBA PNG decodes to the unchanged Group Companion icon pixels", async () => {
  assert.equal(source[25], 2); // The authoritative PWA PNG remains RGB.
  const metadata = await sharp(payload).metadata();
  assert.equal(metadata.format, "png");
  assert.equal(metadata.channels, 4);
  assert.equal(metadata.hasAlpha, true);
  assert.equal(metadata.depth, "uchar");
  const [decodedIcon, decodedSource] = await Promise.all([
    sharp(payload).raw().toBuffer({ resolveWithObject: true }),
    sharp(source).ensureAlpha().raw().toBuffer({ resolveWithObject: true }),
  ]);
  assert.equal(decodedIcon.info.width, icon[6] || 256);
  assert.equal(decodedIcon.info.height, icon[7] || 256);
  assert.equal(decodedIcon.info.channels, 4);
  assert.deepEqual(decodedIcon.info, decodedSource.info);
  assert.deepEqual(decodedIcon.data, decodedSource.data);
});
