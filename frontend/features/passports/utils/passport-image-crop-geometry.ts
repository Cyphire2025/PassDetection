export type CropRotation = number;
export type CropDragMode = "move" | "nw" | "ne" | "sw" | "se";

export interface NormalizedCropGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: CropRotation;
}

export const MIN_CROP_SIZE = 0.08;
export const MIN_FINE_ROTATION = -45;
export const MAX_FINE_ROTATION = 45;

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
    rotation_degrees: normalizeRotationDegrees(source.rotation_degrees + 90),
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
    rotation_degrees: normalizeRotationDegrees(source.rotation_degrees),
  };
}

export function normalizeRotationDegrees(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return ((Math.round(value) % 360) + 360) % 360;
}

export function fineRotationOffset(rotationDegrees: number): number {
  const normalized = normalizeRotationDegrees(rotationDegrees);
  const nearestQuarterTurn = Math.floor((normalized + 44) / 90) * 90;
  return normalized - nearestQuarterTurn;
}

export function rotatedImageBounds(
  width: number,
  height: number,
  rotationDegrees: number,
) {
  const radians = (normalizeRotationDegrees(rotationDegrees) * Math.PI) / 180;
  const rawCosine = Math.abs(Math.cos(radians));
  const rawSine = Math.abs(Math.sin(radians));
  const cosine = rawCosine < 1e-10 ? 0 : rawCosine;
  const sine = rawSine < 1e-10 ? 0 : rawSine;
  return {
    width: Math.max(1, Math.ceil((width * cosine) + (height * sine))),
    height: Math.max(1, Math.ceil((width * sine) + (height * cosine))),
  };
}

function quantize(value: number) {
  return Math.round(value * 100_000_000) / 100_000_000;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}
