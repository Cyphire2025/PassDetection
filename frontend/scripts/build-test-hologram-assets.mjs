/* Offline preparation: keep sampling, topology work and large fields off phones. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import ts from "typescript";
import sharp from "sharp";
import * as THREE from "three";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const loaded = new Map();
function load(file) {
  const absolute = path.resolve(file);
  if (loaded.has(absolute)) return loaded.get(absolute).exports;
  const record = { exports: {} }; loaded.set(absolute, record);
  const output = ts.transpileModule(fs.readFileSync(absolute, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function("require", "module", "exports", output)((name) => {
    if (name.startsWith(".")) return load(path.resolve(path.dirname(absolute), `${name}.ts`));
    if (name === "three") return THREE;
    throw new Error(`Unexpected asset dependency: ${name}`);
  }, record, record.exports);
  return record.exports;
}
const base = path.join(root, "features/ai/components");
const { decodeHumanHead } = load(path.join(base, "human-head-geometry.ts"));
const { prepareTestHead } = load(path.join(base, "test-hologram-adult-head.ts"));
const { sampleHead, HEAD_ATTRIBUTES } = load(path.join(base, "test-hologram-particles.ts"));
const directory = path.join(root, "public/ai/human-head");
const source = Uint8Array.from(fs.readFileSync(path.join(directory, "head-v1.bin"))).buffer;
const count = 208 * 208;
const manifest = { version: 2, count, attributes: HEAD_ATTRIBUTES, assets: {} };
for (const appearance of ["female", "male"]) {
  const started = performance.now();
  const arrays = sampleHead(prepareTestHead(decodeHumanHead(source, appearance), appearance), count);
  // A deterministic permutation distributes surface/interior and facial features
  // through every prefix, so drawRange can adapt without gaps or new downloads.
  const order = Array.from({ length: count }, (_, i) => i);
  let seed = 319;
  for (let i = count - 1; i > 0; i--) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const j = Math.floor(seed / 4294967296 * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  const header = 16 + arrays.length * 4;
  // Positions retain 16-bit silhouette precision. Normal/morph/detail deltas
  // use signed bytes: their maximum quantization error is below a screen pixel.
  const buffer = Buffer.alloc(header + count * 3 * (arrays.length + 1));
  buffer.write("GCPART02"); buffer.writeUInt32LE(count, 8); buffer.writeUInt32LE(arrays.length, 12);
  let offset = header;
  arrays.forEach((array, attribute) => {
    const maximum = array.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
    const width = attribute === 0 ? 2 : 1;
    const scale = Math.max(maximum / (width === 2 ? 32767 : 127), 1e-9);
    buffer.writeFloatLE(scale, 16 + attribute * 4);
    for (let i = 0; i < count; i++) for (let axis = 0; axis < 3; axis++) {
      const value = Math.round(array[order[i] * 3 + axis] / scale);
      if (width === 2) buffer.writeInt16LE(value, offset); else buffer.writeInt8(value, offset);
      offset += width;
    }
  });
  const packed = gzipSync(buffer, { level: 9 });
  const hash = createHash("sha256").update(packed).digest("hex");
  const file = `particles-${appearance}-${hash.slice(0, 12)}.bin.gz`;
  fs.writeFileSync(path.join(directory, file), packed);
  manifest.assets[appearance] = { file, bytes: packed.length, sha256: hash };
  console.log(`${appearance}: ${packed.length} bytes; ${Math.round(performance.now() - started)}ms offline`);
  await sharp(path.join(directory, `${appearance}-still.png`)).resize({ width: 256 }).webp({ quality: 65 }).toFile(path.join(directory, `${appearance}-preview.webp`));
}
fs.writeFileSync(path.join(directory, "particles-v1.json"), JSON.stringify(manifest, null, 2) + "\n");
const landscape = path.join(root, "public/ai/test-landscape");
const compact = {};
const saveAsset = (key, data, extension) => {
  const hash = createHash("sha256").update(data).digest("hex");
  const file = `${key}-${hash.slice(0, 12)}.${extension}`;
  fs.writeFileSync(path.join(landscape, file), data);
  compact[key] = { file, bytes: data.length, sha256: hash };
};
for (const name of ["mountain", "ground"]) {
  const data = await sharp(path.join(landscape, `${name}-color.webp`)).resize(1024, 1024).webp({ quality: 84, effort: 6 }).toBuffer();
  saveAsset(`${name}-color`, data, "webp");
}
for (const name of ["mountain", "ground", "patch", "grade-rgba16f"]) saveAsset(name, gzipSync(fs.readFileSync(path.join(landscape, `${name}.bin`)), { level: 9 }), "bin.gz");
saveAsset("wind", fs.readFileSync(path.join(landscape, "wind.webp")), "webp");
fs.writeFileSync(path.join(landscape, "compact-v1.json"), JSON.stringify(compact, null, 2) + "\n");
