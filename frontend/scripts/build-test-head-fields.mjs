/* Offline-only exporter. Uses the same reviewed TypeScript preparation as the renderer. */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as THREE from "three";
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, ".."), loaded = new Map(), sources = new Map();
function load(file) {
  const absolute = path.resolve(file);
  if (loaded.has(absolute)) return loaded.get(absolute).exports;
  const source = fs.readFileSync(absolute, "utf8"), record = { exports: {} };
  // Git may check text out with CRLF on Windows; provenance describes the source.
  sources.set(path.relative(root, absolute).replaceAll("\\", "/"), crypto.createHash("sha256").update(source.replace(/\r\n/g, "\n")).digest("hex"));
  loaded.set(absolute, record);
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function("require", "module", "exports", output)((name) => {
    if (name.startsWith(".")) return load(path.resolve(path.dirname(absolute), `${name}.ts`));
    if (name === "three") return THREE;
    throw new Error(`Unexpected offline export dependency: ${name}`);
  }, record, record.exports);
  return record.exports;
}
const option = (name, fallback) => { const index = process.argv.indexOf(name); return index < 0 ? fallback : process.argv[index + 1]; };
const work = path.resolve(option("--work", null) ?? fs.mkdtempSync(path.join(os.tmpdir(), "head-fields-")));
const output = path.resolve(option("--output", path.join(root, "public/ai/human-head")));
const python = option("--python", process.platform === "win32"
  ? path.resolve(root, "../backend/.venv/Scripts/python.exe") : path.resolve(root, "../backend/.venv/bin/python"));
fs.mkdirSync(work, { recursive: true }); fs.mkdirSync(output, { recursive: true });
const base = path.join(root, "features/ai/components");
const { decodeHumanHead, HEAD_MORPHS } = load(path.join(base, "human-head-geometry.ts"));
const { prepareTestHead } = load(path.join(base, "test-hologram-adult-head.ts"));
const { createHeadVolume } = load(path.join(base, "test-hologram-volume.ts"));
const { eyeRegions } = load(path.join(base, "test-hologram-eyes.ts"));
const source = Uint8Array.from(fs.readFileSync(path.join(root, "public/ai/human-head/head-v1.bin"))).buffer;
const sourceHash = crypto.createHash("sha256").update(new Uint8Array(source)).digest("hex");
const side = 64, metadata = { version: 1, side, sourceHash, sources: {}, appearances: {} };
for (const appearance of ["female", "male"]) {
  const start = performance.now(), head = prepareTestHead(decodeHumanHead(source, appearance), appearance);
  const volume = createHeadVolume(head), b = volume.bounds, padding = .14;
  const min = [b.minX - padding, b.minY - padding, b.minZ - padding];
  const size = [b.maxX - b.minX + padding * 2, b.maxY - b.minY + padding * 2, b.maxZ - b.minZ + padding * 2];
  const occupancy = new Uint8Array(side ** 3);
  for (let y = 0; y < side; y++) for (let x = 0; x < side; x++) {
    const intervals = volume.intervals(min[0] + (x + .5) * size[0] / side, min[1] + (y + .5) * size[1] / side);
    for (let z = 0; z < side; z++) {
      const position = min[2] + (z + .5) * size[2] / side;
      occupancy[(z * side + y) * side + x] = intervals.some(({ back, front }) => position > back.z && position < front.z) ? 1 : 0;
    }
  }
  const arrays = { positions: head.positions, normals: head.normals, triangles: head.triangles,
    eyes: eyeRegions(head), detail: head.surfaceDetail, ...head.morphs };
  const entries = {};
  for (const [name, array] of Object.entries(arrays)) {
    const filename = `${appearance}-${name}.bin`;
    fs.writeFileSync(path.join(work, filename), Buffer.from(array.buffer, array.byteOffset, array.byteLength));
    entries[name] = { file: filename, type: name === "triangles" ? "uint16" : "float32", length: array.length };
  }
  fs.writeFileSync(path.join(work, `${appearance}-occupancy.bin`), occupancy);
  metadata.appearances[appearance] = { min, size, arrays: entries, morphs: HEAD_MORPHS,
    occupiedVoxels: occupancy.reduce((sum, value) => sum + value, 0) };
  console.log(`${appearance}: exported ${head.positions.length / 3} vertices and ${side}³ occupancy in ${(performance.now() - start).toFixed(0)}ms`);
}
metadata.sources = Object.fromEntries([...sources].sort(([a], [b]) => a.localeCompare(b)));
fs.writeFileSync(path.join(work, "input.json"), JSON.stringify(metadata, null, 2) + "\n");
const result = spawnSync(python, [path.join(directory, "bake-test-head-fields.py"), "--input", work, "--output", output], { stdio: "inherit" });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
