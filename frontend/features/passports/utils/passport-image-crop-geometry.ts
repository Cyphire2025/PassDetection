export type CropRotation = 0 | 90 | 180 | 270;
export type CropDragMode = "move" | "nw" | "ne" | "sw" | "se";

export interface NormalizedCropGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: CropRotation;
}

export const MIN_CROP_SIZE = 0.08;

export function resizeCrop(
  source: NormalizedCropGeometry,
  mode: CropDragMode,
  deltaX: number,
  deltaY: number,
): NormalizedCropGeometry {
  if (mode === "move") {
    return normalizeCrop({
      ...source,
      x: clamp(source.x + deltaX, 0, 1 - source.width),
      y: clamp(source.y + deltaY, 0, 1 - source.height),
    });
  }
  const right = source.x + source.width;
  const bottom = source.y + source.height;
  let left = source.x;
  let top = source.y;
  let nextRight = right;
  let nextBottom = bottom;
  if (mode.includes("w")) left = clamp(source.x + deltaX, 0, right - MIN_CROP_SIZE);
  if (mode.includes("e")) nextRight = clamp(right + deltaX, source.x + MIN_CROP_SIZE, 1);
  if (mode.includes("n")) top = clamp(source.y + deltaY, 0, bottom - MIN_CROP_SIZE);
  if (mode.includes("s")) nextBottom = clamp(bottom + deltaY, source.y + MIN_CROP_SIZE, 1);
  return normalizeCrop({
    ...source,
    x: left,
    y: top,
    width: nextRight - left,
    height: nextBottom - top,
  });
}

export function rotateCropClockwise(
  source: NormalizedCropGeometry,
): NormalizedCropGeometry {
  return normalizeCrop({
    x: 1 - source.y - source.height,
    y: source.x,
    width: source.height,
    height: source.width,
    rotation_degrees: ((source.rotation_degrees + 90) % 360) as CropRotation,
  });
}

export function normalizeCrop(
  source: NormalizedCropGeometry,
): NormalizedCropGeometry {
  const width = quantize(clamp(source.width, MIN_CROP_SIZE, 1));
  const height = quantize(clamp(source.height, MIN_CROP_SIZE, 1));
  return {
    ...source,
    x: quantize(clamp(source.x, 0, 1 - width)),
    y: quantize(clamp(source.y, 0, 1 - height)),
    width,
    height,
  };
}

function quantize(value: number) {
  return Math.round(value * 100_000_000) / 100_000_000;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}
