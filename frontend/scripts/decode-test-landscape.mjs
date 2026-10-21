import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { read } from "three/addons/libs/ktx-parse.module.js";
import { ZSTDDecoder } from "three/addons/libs/zstddec.module.js";

// Offline only. The decoders come from the pinned Three npm package; no Igloo
// application JavaScript is executed or copied into this build script.
const root = new URL("../public/ai/test-landscape/", import.meta.url), derived = [];
const record = (file, source, data, transform, metadata = {}) => {
  writeFileSync(new URL(file, root), data);
  derived.push({ file, source, transform, rebuild: "node scripts/decode-test-landscape.mjs", bytes: data.byteLength, sha256: createHash("sha256").update(data).digest("hex"), ...metadata });
};
async function decoder(modulePath, wasmPath) {
  const moduleFile = fileURLToPath(new URL(`../node_modules/three/examples/jsm/libs/${modulePath}`, import.meta.url)), host = { exports: {} };
  new Function("module", "exports", "require", "__dirname", "__filename", readFileSync(moduleFile, "utf8"))(host, host.exports, createRequire(import.meta.url), dirname(moduleFile), moduleFile);
  return host.exports({ wasmBinary: readFileSync(new URL(`../node_modules/three/examples/jsm/libs/${wasmPath}`, import.meta.url)) });
}
const draco = await decoder("draco/draco_wasm_wrapper.js", "draco/draco_decoder.wasm");
for (const name of ["mountain", "ground", "patch"]) {
  const bytes = new Int8Array(readFileSync(new URL(`${name}.drc`, root))), decoder = new draco.Decoder(), mesh = new draco.Mesh();
  try {
    const status = decoder.DecodeArrayToMesh(bytes, bytes.byteLength, mesh);
    if (!status.ok()) throw new Error(status.error_msg());
    const count = mesh.num_points(), indices = mesh.num_faces() * 3;
    if (count > 65535) throw new Error("Terrain exceeds the reviewed Uint16 vertex bound");
    const output = Buffer.alloc(16 + count * 32 + indices * 2);
    output.write("LND1"); output.writeUInt32LE(count, 4); output.writeUInt32LE(indices, 8);
    let offset = 16;
    for (const [semantic, components] of [[draco.POSITION, 3], [draco.NORMAL, 3], [draco.TEX_COORD, 2]]) {
      const attribute = decoder.GetAttribute(mesh, decoder.GetAttributeId(mesh, semantic)), values = new draco.DracoFloat32Array();
      try {
        if (attribute.num_components() !== components || !decoder.GetAttributeFloatForAllPoints(mesh, attribute, values)) throw new Error("Invalid terrain attribute");
        for (let i = 0; i < values.size(); i++, offset += 4) output.writeFloatLE(values.GetValue(i), offset);
      } finally { draco.destroy(values); }
    }
    const face = new draco.DracoInt32Array();
    try {
      for (let i = 0; i < mesh.num_faces(); i++) {
        decoder.GetFaceFromMesh(mesh, i, face);
        for (let j = 0; j < 3; j++, offset += 2) output.writeUInt16LE(face.GetValue(j), offset);
      }
    } finally { draco.destroy(face); }
    record(`${name}.bin`, `${name}.drc`, output, "Decoded original POSITION/NORMAL/UV Float32 values and triangle indices; no geometry edits or quantization.");
  } finally { draco.destroy(mesh); draco.destroy(decoder); }
}
const container = read(readFileSync(new URL("grade.ktx2", root)));
if (container.vkFormat !== 97 || container.pixelWidth !== 32 || container.pixelHeight !== 32 || container.pixelDepth !== 32 || container.supercompressionScheme !== 2 || container.levels.length !== 1) throw new Error("Unexpected source LUT format");
const zstd = new ZSTDDecoder(); await zstd.init();
const level = container.levels[0], decoded = zstd.decode(level.levelData, level.uncompressedByteLength);
if (decoded.byteLength !== 32 * 32 * 32 * 4 * 2) throw new Error("Invalid LUT texel byte length");
record("grade-rgba16f.bin", "grade.ktx2", decoded, "Lossless decompression of the sole KTX2 Zstd level; unchanged little-endian RGBA16F texels, 32×32×32.");
const basis = await decoder("basis/basis_transcoder.js", "basis/basis_transcoder.wasm");
basis.initializeBasis();
for (const name of ["mountain-color", "ground-color", "wind"]) {
  const file = new basis.KTX2File(new Uint8Array(readFileSync(new URL(`${name}.ktx2`, root))));
  try {
    const width = file.getWidth(), height = file.getHeight(), expected = name === "wind" ? 256 : 2048;
    if (!file.isValid() || width !== expected || height !== expected || file.getFaces() !== 1 || file.getLayers() > 1 || !file.startTranscoding()) throw new Error(`Unexpected texture format: ${name}`);
    const rgba = new Uint8Array(file.getImageTranscodedSizeInBytes(0, 0, 0, 13));
    if (rgba.byteLength !== width * height * 4 || !file.transcodeImage(rgba, 0, 0, 0, 13, 0, -1, -1)) throw new Error(`Texture decode failed: ${name}`);
    const image = sharp(rgba, { raw: { width, height, channels: 4 } });
    const png = await image.clone().png({ compressionLevel: 9 }).toBuffer();
    const webp = await image.clone().webp({ lossless: true, effort: 6 }).toBuffer();
    const extension = webp.byteLength < png.byteLength ? "webp" : "png", encoded = extension === "webp" ? webp : png;
    const restored = await sharp(encoded).ensureAlpha().raw().toBuffer();
    if (!restored.equals(Buffer.from(rgba))) throw new Error(`Texture encoding changed decoded RGBA pixels: ${name}`);
    record(`${name}.${extension}`, `${name}.ktx2`, encoded, "Base level decoded by pinned Basis Universal to RGBA32 and encoded losslessly without resizing, orientation changes or color conversion. Pixel equality checked after decoding the image; browser regenerates mipmaps.", {
      width, height, rgba_sha256: createHash("sha256").update(rgba).digest("hex"), compared_bytes: { png: png.byteLength, lossless_webp: webp.byteLength },
    });
  } finally { file.close(); file.delete(); }
}
const manifestPath = new URL("provenance.json", root), manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
manifest.assets = manifest.assets.filter((asset) => !asset.file.startsWith("decoders/"));
manifest.build_tools.texture_decoder = "examples/jsm/libs/basis/basis_transcoder.js + basis_transcoder.wasm (Apache-2.0), offline only";
manifest.build_tools.image_encoder = `sharp@${sharp.versions.sharp}; lossless PNG/WebP compared, round-trip RGBA equality verified`;
manifest.build_tools.runtime = "Ordinary same-origin fetch and native ImageBitmap decoding. No runtime decoder JavaScript, WASM, workers, data: requests or string evaluation.";
manifest.derived = derived; writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
console.log(JSON.stringify(derived.map(({ file, bytes, sha256 }) => ({ file, bytes, sha256 }))));
