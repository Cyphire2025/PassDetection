"use client";

import {
  normalizeCrop,
  type CropRotation,
  type NormalizedCropGeometry,
} from "../../passports/utils/passport-image-crop-geometry";
import {
  croppedPassportFileName,
  passportCropOutputSize,
  passportCropPixelBounds as normalizedPassportCropPixelBounds,
  rotatedPassportImageSize,
  type PassportCropPixelBounds,
  type PassportImageSize,
} from "./passport-manual-crop-math";

export {
  croppedPassportFileName,
  passportCropOutputSize,
  rotatedPassportImageSize,
};

export type PassportManualCrop = NormalizedCropGeometry;
export type { PassportCropPixelBounds, PassportImageSize };

export const FULL_PASSPORT_CROP: PassportManualCrop = {
  x: 0,
  y: 0,
  width: 1,
  height: 1,
  rotation_degrees: 0,
};

const PREVIEW_MAX_DIMENSION = 1_400;
const JPEG_QUALITY = 0.94;

export function passportCropPixelBounds(
  crop: PassportManualCrop,
  rotatedSize: PassportImageSize,
): PassportCropPixelBounds {
  return normalizedPassportCropPixelBounds(normalizeCrop(crop), rotatedSize);
}

export function drawPassportCropPreview(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  rotation: CropRotation,
) {
  const rotatedSize = rotatedPassportImageSize(
    image.naturalWidth,
    image.naturalHeight,
    rotation,
  );
  const scale = Math.min(
    1,
    PREVIEW_MAX_DIMENSION / Math.max(rotatedSize.width, rotatedSize.height),
  );
  canvas.width = Math.max(1, Math.round(rotatedSize.width * scale));
  canvas.height = Math.max(1, Math.round(rotatedSize.height * scale));
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("This browser cannot display the crop preview.");
  }
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.save();
  context.scale(scale, scale);
  drawRotatedPassportImage(context, image, rotation, rotatedSize);
  context.restore();
}

export async function createCroppedPassportFile(
  sourceFile: File,
  image: HTMLImageElement,
  crop: PassportManualCrop,
): Promise<File> {
  if (image.naturalWidth <= 0 || image.naturalHeight <= 0) {
    throw new Error("The passport image is not ready to crop.");
  }
  const normalized = normalizeCrop(crop);
  const rotatedSize = rotatedPassportImageSize(
    image.naturalWidth,
    image.naturalHeight,
    normalized.rotation_degrees,
  );
  const bounds = passportCropPixelBounds(normalized, rotatedSize);
  const outputSize = passportCropOutputSize(bounds);
  const canvas = document.createElement("canvas");
  canvas.width = outputSize.width;
  canvas.height = outputSize.height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("This browser cannot prepare the cropped passport image.");
  }

  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.save();
  context.scale(
    outputSize.width / bounds.width,
    outputSize.height / bounds.height,
  );
  context.translate(-bounds.left, -bounds.top);
  drawRotatedPassportImage(
    context,
    image,
    normalized.rotation_degrees,
    rotatedSize,
  );
  context.restore();

  const blob = await canvasToJpeg(canvas);
  return new File(
    [blob],
    croppedPassportFileName(sourceFile.name),
    {
      type: "image/jpeg",
      lastModified: Date.now(),
    },
  );
}

function drawRotatedPassportImage(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  rotation: CropRotation,
  rotatedSize: PassportImageSize,
) {
  context.save();
  if (rotation === 90) {
    context.translate(rotatedSize.width, 0);
    context.rotate(Math.PI / 2);
  } else if (rotation === 180) {
    context.translate(rotatedSize.width, rotatedSize.height);
    context.rotate(Math.PI);
  } else if (rotation === 270) {
    context.translate(0, rotatedSize.height);
    context.rotate(-Math.PI / 2);
  }
  context.drawImage(image, 0, 0);
  context.restore();
}

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("The cropped passport image could not be saved."));
        }
      },
      "image/jpeg",
      JPEG_QUALITY,
    );
  });
}
