export const HEAD_FIELD_SIDE = 64;
export const HEAD_FIELD_COUNT = 9;
export const HEAD_FIELD_HEADER = 128;
export const HEAD_FIELD_VALUES = HEAD_FIELD_SIDE ** 3 * 4;
export const HEAD_FIELD_BYTES = HEAD_FIELD_HEADER + HEAD_FIELD_VALUES * HEAD_FIELD_COUNT * 2;
export type FieldAppearance = "female" | "male";
export type HeadFieldData = { arrays: Uint16Array[]; min: [number, number, number]; size: [number, number, number] };

/** Little-endian, x-fastest RGBA16F. Reject malformed payloads before GPU allocation. */
export function decodeHeadFieldData(buffer: ArrayBuffer, appearance: FieldAppearance): HeadFieldData {
  if (buffer.byteLength !== HEAD_FIELD_BYTES) throw new Error("Invalid head field asset size");
  const header = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 8));
  if (magic !== "GCHSDF01" || header.getUint32(8, true) !== 1
    || header.getUint32(12, true) !== HEAD_FIELD_SIDE || header.getUint32(16, true) !== HEAD_FIELD_COUNT
    || header.getUint32(20, true) !== (appearance === "female" ? 0 : 1)
    || header.getUint32(24, true) !== HEAD_FIELD_BYTES - HEAD_FIELD_HEADER) throw new Error("Invalid head field layout");
  const min = [0, 1, 2].map((axis) => header.getFloat32(32 + axis * 4, true)) as HeadFieldData["min"];
  const size = [0, 1, 2].map((axis) => header.getFloat32(44 + axis * 4, true)) as HeadFieldData["size"];
  if (min.some((value) => !Number.isFinite(value) || Math.abs(value) > 4)
    || size.some((value) => !Number.isFinite(value) || value < .1 || value > 6)) throw new Error("Invalid head field bounds");
  const arrays = Array.from({ length: HEAD_FIELD_COUNT }, (_, field) =>
    new Uint16Array(buffer, HEAD_FIELD_HEADER + field * HEAD_FIELD_VALUES * 2, HEAD_FIELD_VALUES));
  for (const values of arrays) for (const value of values) {
    // Half-float exponent31 represents infinity/NaN. Neither is a valid field sample.
    if ((value & 0x7c00) === 0x7c00) throw new Error("Non-finite head field sample");
  }
  return { arrays, min, size };
}
