import manifest from "../../../public/ai/human-head/particles-v1.json";

export const PARTICLE_ATTRIBUTES = ["position", "normal", "jawShape", "roundShape", "wideShape", "closureShape", "fricativeShape", "blinkShape", "eyeRegion", "surfaceDetail"] as const;
const MAX_BYTES = 3_000_000;

export function decodeParticleHead(buffer: ArrayBuffer): Float32Array[] {
  if (buffer.byteLength < 56 || buffer.byteLength > MAX_BYTES) throw new Error("Invalid particle asset size");
  const header = new DataView(buffer), count = header.getUint32(8, true), attributes = header.getUint32(12, true);
  if (String.fromCharCode(...new Uint8Array(buffer, 0, 8)) !== "GCPART02" || count !== manifest.count
    || attributes !== PARTICLE_ATTRIBUTES.length || buffer.byteLength !== 16 + attributes * 4 + count * (attributes + 1) * 3) throw new Error("Invalid particle asset layout");
  let offset = 16 + attributes * 4;
  return PARTICLE_ATTRIBUTES.map((_, attribute) => {
    const scale = header.getFloat32(16 + attribute * 4, true);
    if (!Number.isFinite(scale) || scale <= 0 || scale > .1) throw new Error("Invalid particle asset scale");
    const values = new Float32Array(count * 3), width = attribute === 0 ? 2 : 1;
    for (let i = 0; i < values.length; i++, offset += width) values[i] = (width === 2 ? header.getInt16(offset, true) : header.getInt8(offset)) * scale;
    return values;
  });
}

async function boundedBytes(stream: ReadableStream<Uint8Array>, signal: AbortSignal) {
  const reader = stream.getReader(), chunks: Uint8Array[] = [];
  let length = 0;
  const cancel = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    signal.throwIfAborted();
    while (true) {
      const { done, value } = await reader.read(); signal.throwIfAborted();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_BYTES) { await reader.cancel(); throw new Error("Particle asset exceeds budget"); }
      chunks.push(value);
    }
    const result = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
    return result.buffer;
  } finally { signal.removeEventListener("abort", cancel); reader.releaseLock(); }
}

export async function loadParticleHead(appearance: "female" | "male", signal: AbortSignal) {
  const controller = new AbortController(), bounded = controller.signal;
  const abort = () => controller.abort(signal.reason);
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const deadline = setTimeout(() => controller.abort(new Error("Particle preparation timed out")), 15_000);
  try {
    const response = await fetch(`/ai/human-head/${manifest.assets[appearance].file}`, { signal: bounded, cache: "force-cache", priority: "high" });
    if (!response.ok || !response.body) throw new Error("Particle head unavailable");
    const packed = await boundedBytes(response.body, bounded), bytes = new Uint8Array(packed);
    // Production uses native HTTP gzip decoding. This branch also supports a
    // plain static preview server that serves the compressed file verbatim.
    const expanded = bytes[0] === 0x1f && bytes[1] === 0x8b
      ? await boundedBytes(new Blob([packed]).stream().pipeThrough(new DecompressionStream("gzip")), bounded) : packed;
    bounded.throwIfAborted();
    return decodeParticleHead(expanded);
  } finally { clearTimeout(deadline); signal.removeEventListener("abort", abort); }
}
