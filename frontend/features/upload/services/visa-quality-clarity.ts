import type {
  VisaPhotoFaceGeometry, VisaPhotoClarityStatus, VisaPhotoClarityMetrics, PixelBounds,
} from "./visa-quality.types.ts";

export function evaluateVisaPhotoClarity(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  face: VisaPhotoFaceGeometry,
): VisaPhotoClarityMetrics {
  // Stay inside the detector's face box so a bright wall around a dark face,
  // or a sharp face/background boundary around an otherwise blurred face,
  // cannot make the facial exposure and sharpness checks look acceptable.
  const bounds = facePixelBounds(face, width, height, 0.38, 0.38);
  if (
    width <= 0
    || height <= 0
    || pixels.length < width * height * 4
    || bounds.right - bounds.left < 3
    || bounds.bottom - bounds.top < 3
  ) {
    return {
      status: "blurry",
      averageLuminance: 0,
      darkPixelRatio: 1,
      brightPixelRatio: 0,
      averageGradient: 0,
      highGradientRatio: 0,
    };
  }

  let samples = 0;
  let luminanceTotal = 0;
  let darkPixels = 0;
  let brightPixels = 0;
  let gradientSamples = 0;
  let gradientTotal = 0;
  let highGradientPixels = 0;
  const faceCenterX = face.centerX * width;
  const faceCenterY = face.centerY * height;
  const faceRadiusX = Math.max(1, face.width * width * 0.38);
  const faceRadiusY = Math.max(1, face.height * height * 0.38);

  for (let y = bounds.top; y <= bounds.bottom; y += 1) {
    for (let x = bounds.left; x <= bounds.right; x += 1) {
      const insideCentralFace = ((x - faceCenterX) / faceRadiusX) ** 2
        + ((y - faceCenterY) / faceRadiusY) ** 2 <= 1;
      if (!insideCentralFace) continue;
      const luminance = pixelLuminance(pixels, width, x, y);
      samples += 1;
      luminanceTotal += luminance;
      if (luminance < 32) darkPixels += 1;
      if (luminance > 246) brightPixels += 1;
      if (
        x <= bounds.left
        || x >= bounds.right
        || y <= bounds.top
        || y >= bounds.bottom
      ) {
        continue;
      }
      const horizontal = Math.abs(
        pixelLuminance(pixels, width, x + 1, y)
        - pixelLuminance(pixels, width, x - 1, y),
      );
      const vertical = Math.abs(
        pixelLuminance(pixels, width, x, y + 1)
        - pixelLuminance(pixels, width, x, y - 1),
      );
      const gradient = (horizontal + vertical) / 2;
      gradientSamples += 1;
      gradientTotal += gradient;
      if (gradient >= 24) highGradientPixels += 1;
    }
  }

  const averageLuminance = luminanceTotal / Math.max(1, samples);
  const darkPixelRatio = darkPixels / Math.max(1, samples);
  const brightPixelRatio = brightPixels / Math.max(1, samples);
  const averageGradient = gradientTotal / Math.max(1, gradientSamples);
  const highGradientRatio = highGradientPixels / Math.max(1, gradientSamples);
  const status: VisaPhotoClarityStatus = averageLuminance < 58 && darkPixelRatio > 0.34
    ? "too_dark"
    : averageLuminance > 226 && brightPixelRatio > 0.34
      ? "too_bright"
      : averageGradient < 2.8 && highGradientRatio < 0.018
        ? "blurry"
        : "good";

  return {
    status,
    averageLuminance,
    darkPixelRatio,
    brightPixelRatio,
    averageGradient,
    highGradientRatio,
  };
}

function facePixelBounds(
  face: VisaPhotoFaceGeometry,
  width: number,
  height: number,
  horizontalScale: number,
  verticalScale: number,
): PixelBounds {
  return {
    left: clampPixel((face.centerX - face.width * horizontalScale) * width, width),
    right: clampPixel((face.centerX + face.width * horizontalScale) * width, width),
    top: clampPixel((face.centerY - face.height * verticalScale) * height, height),
    bottom: clampPixel((face.centerY + face.height * verticalScale) * height, height),
  };
}

function clampPixel(value: number, extent: number): number {
  return Math.min(extent - 1, Math.max(0, Math.round(value)));
}

function pixelLuminance(
  pixels: Uint8ClampedArray,
  width: number,
  x: number,
  y: number,
): number {
  const index = (y * width + x) * 4;
  return 0.2126 * pixels[index]
    + 0.7152 * pixels[index + 1]
    + 0.0722 * pixels[index + 2];
}
