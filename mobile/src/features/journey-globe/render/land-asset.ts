import { base64 } from '@scure/base';

import bundledMask from '../../../../assets/maps/earth-land-mask.json';

export type LandMask = { width: number; height: number; pixels: Uint8Array };
type PackedLandMask = { encoding: string; width: number; height: number; data: string };

/** Decode the bundled geography without Android drawable or native PNG decoding. */
export function decodeLandMask(packed: PackedLandMask): LandMask {
  const { width, height } = packed;
  if (packed.encoding !== 'rle8-v1' || !Number.isInteger(width) || width < 4 || width > 2048
    || (width & (width - 1)) !== 0 || height !== width / 2) {
    throw new Error('Invalid globe geography dimensions or encoding');
  }
  const length = width * height;
  if (packed.data.length > length * 4) throw new Error('Invalid globe geography payload');
  const runs = base64.decode(packed.data);
  if (runs.length % 3 !== 0) throw new Error('Truncated globe geography');
  const pixels = new Uint8Array(length);
  let offset = 0;
  let landPixels = 0;
  for (let index = 0; index < runs.length; index += 3) {
    const value = runs[index]!;
    const count = (runs[index + 1]! << 8) | runs[index + 2]!;
    if (!count || offset + count > length) throw new Error('Invalid globe geography run');
    pixels.fill(value, offset, offset + count);
    offset += count;
    if (value >= 128) landPixels += count;
  }
  // A missing/corrupt mask must never be accepted as a successfully loaded ocean.
  if (offset !== length || landPixels < length * 0.15 || landPixels > length * 0.5) {
    throw new Error('Incomplete globe geography');
  }
  return { width, height, pixels };
}

let loadedMask: LandMask | undefined;

export function loadLandMask(): LandMask {
  loadedMask ??= decodeLandMask(bundledMask);
  return loadedMask;
}
