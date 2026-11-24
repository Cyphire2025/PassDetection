export const HEAD_MORPHS = ["jaw", "round", "wide", "closure", "fricative", "blink"] as const;
export type HeadMorph = typeof HEAD_MORPHS[number];
export type HumanHeadGeometry = {
  positions: Float32Array;
  normals: Float32Array;
  triangles: Uint16Array;
  edges: Uint16Array;
  morphs: Record<HeadMorph, Float32Array>;
};

const HEADER_BYTES = 64;
const ARRAY_COUNT = 10;
const ASSET_URL = "/ai/human-head/head-v1.bin";

/** Real CC0 head/neck geometry, Y-up and +Z-forward. Morphs are additive deltas.
 * The two appearances share topology and authored facial shapes. See the asset's
 * README for provenance, coordinates and the reproducible binary specification.
 */
export function decodeHumanHead(buffer: ArrayBuffer, appearance: "male" | "female"): HumanHeadGeometry {
  if (buffer.byteLength < HEADER_BYTES || buffer.byteLength > 4_000_000) throw new Error("Invalid head asset size");
  const data = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 8));
  const vertices = data.getUint32(8, true);
  const triangleCount = data.getUint32(12, true);
  const edgeCount = data.getUint32(16, true);
  const arrays = data.getUint32(20, true);
  const values = vertices * 3;
  const expected = HEADER_BYTES + values * ARRAY_COUNT * 2 + (triangleCount + edgeCount) * 2;
  if (magic !== "GCHEAD01" || vertices < 3 || vertices >= 65_536 || arrays !== ARRAY_COUNT
    || triangleCount < 3 || triangleCount % 3 !== 0 || edgeCount < 2 || edgeCount % 2 !== 0
    || expected !== buffer.byteLength) throw new Error("Invalid head asset layout");
  const scales = Array.from({ length: ARRAY_COUNT }, (_, index) => data.getFloat32(24 + index * 4, true));
  if (scales.some((scale) => !Number.isFinite(scale) || scale <= 0 || scale > 1)) throw new Error("Invalid head asset scale");
  const decode = (index: number) => {
    const result = new Float32Array(values);
    const offset = HEADER_BYTES + index * values * 2;
    for (let i = 0; i < values; i++) result[i] = data.getInt16(offset + i * 2, true) * scales[index];
    return result;
  };
  const indices = (offset: number, count: number) => {
    const result = new Uint16Array(count);
    for (let i = 0; i < count; i++) {
      result[i] = data.getUint16(offset + i * 2, true);
      if (result[i] >= vertices) throw new Error("Invalid head asset index");
    }
    return result;
  };
  const indexOffset = HEADER_BYTES + values * ARRAY_COUNT * 2;
  const variant = appearance === "male" ? 2 : 0;
  const morphs = Object.fromEntries(HEAD_MORPHS.map((name, i) => [name, decode(i + 4)])) as HumanHeadGeometry["morphs"];
  return {
    positions: decode(variant), normals: decode(variant + 1), morphs,
    triangles: indices(indexOffset, triangleCount),
    edges: indices(indexOffset + triangleCount * 2, edgeCount),
  };
}

export async function loadHumanHead(appearance: "male" | "female", signal?: AbortSignal): Promise<HumanHeadGeometry> {
  const response = await fetch(ASSET_URL, { signal, cache: "force-cache" });
  if (!response.ok) throw new Error("Human head asset unavailable");
  return decodeHumanHead(await response.arrayBuffer(), appearance);
}
