export type PassportCropRotation = number;

export interface PassportCropGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation_degrees: PassportCropRotation;
}

export interface PassportCropPixelBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface PassportImageSize {
  width: number;
  height: number;
}

export function rotatedPassportImageSize(
  width: number,
  height: number,
  rotation: PassportCropRotation,
): PassportImageSize {
  const normalizedRotation = normalizeRotationDegrees(rotation);
  if (normalizedRotation === 90 || normalizedRotation === 270) {
    return { width: height, height: width };
  }
  if (normalizedRotation === 0 || normalizedRotation === 180) {
    return { width, height };
  }
  const radians = (normalizedRotation * Math.PI) / 180;
  const cosine = Math.abs(Math.cos(radians));
  const sine = Math.abs(Math.sin(radians));
  return {
    width: Math.max(1, Math.ceil((width * cosine) + (height * sine))),
    height: Math.max(1, Math.ceil((width * sine) + (height * cosine))),
  };
}

export function passportCropPixelBounds(
  crop: PassportCropGeometry,
  rotatedSize: PassportImageSize,
): PassportCropPixelBounds {
  const left = Math.max(
    0,
    Math.min(rotatedSize.width - 1, Math.floor(crop.x * rotatedSize.width)),
  );
  const top = Math.max(
    0,
    Math.min(rotatedSize.height - 1, Math.floor(crop.y * rotatedSize.height)),
  );
  const right = Math.max(
    left + 1,
    Math.min(
      rotatedSize.width,
      Math.ceil((crop.x + crop.width) * rotatedSize.width),
    ),
  );
  const bottom = Math.max(
    top + 1,
    Math.min(
      rotatedSize.height,
      Math.ceil((crop.y + crop.height) * rotatedSize.height),
    ),
  );
  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
  };
}

export function passportCropOutputSize(
  bounds: Pick<PassportCropPixelBounds, "width" | "height">,
  maximumDimension = 2_400,
): PassportImageSize {
  const scale = Math.min(
    1,
    maximumDimension / Math.max(1, bounds.width, bounds.height),
  );
  return {
    width: Math.max(1, Math.round(bounds.width * scale)),
    height: Math.max(1, Math.round(bounds.height * scale)),
  };
}

export function croppedPassportFileName(fileName: string): string {
  const baseName = fileName.replace(/\.[^./\\]+$/, "").trim() || "passport";
  return `${baseName}-cropped.jpg`;
}

function normalizeRotationDegrees(rotation: number): number {
  if (!Number.isFinite(rotation)) return 0;
  return ((Math.round(rotation) % 360) + 360) % 360;
}
