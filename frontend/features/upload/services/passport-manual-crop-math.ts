export type PassportCropRotation = 0 | 90 | 180 | 270;

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
  const swapsAxes = rotation === 90 || rotation === 270;
  return {
    width: swapsAxes ? height : width,
    height: swapsAxes ? width : height,
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
