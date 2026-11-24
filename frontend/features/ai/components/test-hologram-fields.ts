import * as THREE from "three";
import fieldManifest from "../../../public/ai/human-head/fields-v1.json";
import { HEAD_MORPHS, type HeadMorph } from "./human-head-geometry";
import { decodeHeadFieldData, HEAD_FIELD_BYTES, HEAD_FIELD_SIDE, type FieldAppearance } from "./test-head-field-format";

export type HeadFields = {
  field: THREE.Data3DTexture;
  morphs: Record<HeadMorph, THREE.Data3DTexture>;
  eyes: THREE.Data3DTexture;
  detail: THREE.Data3DTexture;
  bounds: { min: THREE.Vector3; size: THREE.Vector3 };
  dispose(): void;
};

export function headFieldUniforms(fields: HeadFields): Record<string, THREE.IUniform> {
  return { sdfVolume: { value: fields.field }, sdfEyes: { value: fields.eyes }, sdfDetail: { value: fields.detail },
    sdfMin: { value: fields.bounds.min }, sdfSize: { value: fields.bounds.size },
    ...Object.fromEntries(HEAD_MORPHS.map((name) => [
      `sdf${name[0].toUpperCase()}${name.slice(1)}`, { value: fields.morphs[name] },
    ])),
  };
}

async function readBounded(stream: ReadableStream<Uint8Array>, maximum: number, signal?: AbortSignal): Promise<ArrayBuffer> {
  const reader = stream.getReader(), chunks: Uint8Array[] = [];
  let length = 0;
  const abort = () => { void reader.cancel(signal?.reason).catch(() => {}); };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    signal?.throwIfAborted();
    while (true) {
      const { value, done } = await reader.read();
      signal?.throwIfAborted();
      if (done) break;
      length += value.byteLength;
      if (length > maximum) { await reader.cancel(); throw new Error("Head field download exceeds its budget"); }
      chunks.push(value);
    }
    const buffer = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.byteLength; }
    return buffer.buffer;
  } finally { signal?.removeEventListener("abort", abort); reader.releaseLock(); }
}

/** No cache of GPU resources: the active renderer owns exactly one appearance. */
async function loadFields(appearance: FieldAppearance, signal: AbortSignal): Promise<HeadFields> {
  signal?.throwIfAborted();
  const revision = fieldManifest.assets[appearance].sha256.slice(0, 16);
  const response = await fetch(`/ai/human-head/fields-${appearance}-v1.bin.gz?v=${revision}`, { signal, cache: "force-cache" });
  if (!response.ok || !response.body) throw new Error("Head volume asset unavailable");
  const compressed = await readBounded(response.body, HEAD_FIELD_BYTES, signal);
  const bytes = new Uint8Array(compressed);
  // Accept an HTTP server that transparently decompresses the .gz resource too.
  const expanded = bytes[0] === 0x1f && bytes[1] === 0x8b
    ? await readBounded(new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip")), HEAD_FIELD_BYTES, signal)
    : compressed;
  signal?.throwIfAborted();
  const decoded = decodeHeadFieldData(expanded, appearance), textures: THREE.Data3DTexture[] = [];
  try {
    for (const data of decoded.arrays) {
      const texture = new THREE.Data3DTexture(data, HEAD_FIELD_SIDE, HEAD_FIELD_SIDE, HEAD_FIELD_SIDE);
      textures.push(texture);
      texture.format = THREE.RGBAFormat; texture.type = THREE.HalfFloatType;
      texture.minFilter = texture.magFilter = THREE.LinearFilter;
      texture.wrapS = texture.wrapT = texture.wrapR = THREE.ClampToEdgeWrapping;
      texture.colorSpace = THREE.NoColorSpace; texture.unpackAlignment = 1;
      texture.generateMipmaps = false; texture.needsUpdate = true;
    }
    let disposed = false;
    return {
      field: textures[0], eyes: textures[7], detail: textures[8],
      morphs: Object.fromEntries(HEAD_MORPHS.map((name, index) => [name, textures[index + 1]])) as HeadFields["morphs"],
      bounds: { min: new THREE.Vector3(...decoded.min), size: new THREE.Vector3(...decoded.size) },
      dispose() { if (!disposed) { disposed = true; for (const texture of textures) texture.dispose(); } },
    };
  } catch (error) { for (const texture of textures) texture.dispose(); throw error; }
}

export async function loadHeadFields(appearance: FieldAppearance, signal?: AbortSignal): Promise<HeadFields> {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  const deadline = setTimeout(() => controller.abort(new Error("Head volume preparation timed out")), 25_000);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  try { return await loadFields(appearance, controller.signal); }
  finally { clearTimeout(deadline); signal?.removeEventListener("abort", abort); }
}
