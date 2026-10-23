import { BufferAttribute, BufferGeometry, Data3DTexture, HalfFloatType, NearestFilter, NoColorSpace, RepeatWrapping, RGBAFormat, SRGBColorSpace, Texture, type WebGLRenderer } from "three";
import compactAssets from "../../../public/ai/test-landscape/compact-v1.json";

const ROOT = "/ai/test-landscape/";
const LOAD_DEADLINE_MS = 25_000;
export type LandscapeAssets = { mountain: BufferGeometry; ground: BufferGeometry; patch: BufferGeometry; mountainMap: Texture; groundMap: Texture; wind: Texture; grade: Data3DTexture };

export function decodeLandscapeGeometry(buffer: ArrayBuffer) {
  if (buffer.byteLength < 16) throw new Error("Truncated landscape geometry");
  const header = new DataView(buffer), count = header.getUint32(4, true), indices = header.getUint32(8, true);
  if (header.getUint32(0, true) !== 0x31444e4c || count < 3 || count > 65535 || indices < 3 || indices > 500_000 || indices % 3 || buffer.byteLength !== 16 + count * 32 + indices * 2) throw new Error("Invalid landscape geometry");
  const position = new Float32Array(buffer, 16, count * 3), normal = new Float32Array(buffer, 16 + count * 12, count * 3);
  const uv = new Float32Array(buffer, 16 + count * 24, count * 2), triangles = new Uint16Array(buffer, 16 + count * 32, indices);
  if (![position, normal, uv].every((values) => values.every(Number.isFinite)) || !triangles.every((index) => index < count)) throw new Error("Invalid landscape attributes");
  const result = new BufferGeometry();
  result.setAttribute("position", new BufferAttribute(position, 3)); result.setAttribute("normal", new BufferAttribute(normal, 3));
  result.setAttribute("uv", new BufferAttribute(uv, 2)); result.setIndex(new BufferAttribute(triangles, 1)); result.computeBoundingSphere();
  return result;
}

/** Native image decoding, abortable fetches and a deadline for stalled preparation. */
export function loadLandscapeAssets(renderer: WebGLRenderer, compact = false) {
  const abort = new AbortController(), resources = new Set<BufferGeometry | Texture>(), pending = new Set<(reason: Error) => void>();
  let disposed = false;
  const retire = (reason: Error) => {
    if (disposed) return;
    disposed = true; clearTimeout(deadline); abort.abort();
    for (const reject of pending) reject(reason);
    pending.clear();
    for (const resource of resources) resource.dispose();
    resources.clear();
  };
  const deadline = setTimeout(() => retire(new Error("Landscape preparation timed out")), LOAD_DEADLINE_MS);
  const bounded = <T,>(work: Promise<T>) => new Promise<T>((resolve, reject) => {
    pending.add(reject);
    void work.then((value) => { pending.delete(reject); resolve(value); }, (error: unknown) => { pending.delete(reject); reject(error); });
  });
  const bytes = async (file: string) => {
    const key = file.replace(/\.(bin|webp)$/, "") as keyof typeof compactAssets;
    const name = compact ? compactAssets[key].file : file;
    const response = await fetch(`${ROOT}${name}`, { signal: abort.signal, cache: "force-cache" });
    if (!response.ok) throw new Error(`Landscape asset unavailable: ${file}`);
    let buffer = await response.arrayBuffer();
    // Next serves native HTTP gzip; plain static preview servers may not.
    if (name.endsWith(".gz") && new Uint8Array(buffer)[0] === 0x1f)
      buffer = await new Response(new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
    abort.signal.throwIfAborted(); return buffer;
  };
  const own = <T extends BufferGeometry | Texture>(value: T): T => {
    if (disposed) { value.dispose(); throw new DOMException("Landscape retired", "AbortError"); }
    resources.add(value); return value;
  };
  const geometry = (file: string) => bounded(bytes(file).then((buffer) => own(decodeLandscapeGeometry(buffer))));
  const texture = (file: string, size: number) => bounded(bytes(file).then(async (buffer) => {
    const bitmap = await createImageBitmap(new Blob([buffer], { type: "image/webp" }), {
      imageOrientation: "none", premultiplyAlpha: "none", colorSpaceConversion: "none",
    });
    if (disposed || bitmap.width !== size || bitmap.height !== size) {
      bitmap.close();
      if (disposed) throw new DOMException("Landscape retired", "AbortError");
      throw new Error(`Invalid landscape texture: ${file}`);
    }
    const result = new Texture(bitmap);
    // Match the original KTX2 texel/UV orientation; decode and upload do not flip.
    result.flipY = false;
    let closed = false;
    result.addEventListener("dispose", () => { if (!closed) { closed = true; bitmap.close(); } });
    return own(result);
  }));
  const grade = bounded(bytes("grade-rgba16f.bin").then((buffer) => {
    if (buffer.byteLength !== 32 * 32 * 32 * 4 * 2) throw new Error("Invalid landscape color grade");
    const result = new Data3DTexture(new Uint16Array(buffer), 32, 32, 32);
    result.format = RGBAFormat; result.type = HalfFloatType; return own(result);
  }));
  const ready: Promise<LandscapeAssets> = Promise.all([
    geometry("mountain.bin"), geometry("ground.bin"), geometry("patch.bin"),
    texture("mountain-color.webp", compact ? 1024 : 2048),
    texture("ground-color.webp", compact ? 1024 : 2048), texture("wind.webp", 256), grade,
  ]).then(([mountain, ground, patch, mountainMap, groundMap, wind, grade]) => {
    if (disposed) throw new DOMException("Landscape retired", "AbortError");
    for (const map of [mountainMap, groundMap, wind]) {
      map.colorSpace = SRGBColorSpace; map.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy()); map.needsUpdate = true;
    }
    wind.wrapS = wind.wrapT = RepeatWrapping;
    grade.colorSpace = NoColorSpace; grade.minFilter = grade.magFilter = NearestFilter; grade.needsUpdate = true;
    return { mountain, ground, patch, mountainMap, groundMap, wind, grade };
  }).catch((error: unknown) => {
    retire(error instanceof Error ? error : new Error("Landscape decoding failed")); throw error;
  }).finally(() => { clearTimeout(deadline); });
  void ready.catch(() => undefined);
  return { ready, dispose: () => retire(new DOMException("Landscape retired", "AbortError")) };
}
