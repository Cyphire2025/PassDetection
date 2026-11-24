import type { PassportPageSide } from "./passport-camera-guide";
import { toGrayscale } from "./camera-pixel-math.ts";

export function isSafeCorrectedPage(
  canvas: HTMLCanvasElement,
  pageSide: PassportPageSide,
) {
  if (canvas.width < 640 || canvas.height < 440) return false;
  const aspectRatio = canvas.width / Math.max(1, canvas.height);
  if (aspectRatio < 1.08 || aspectRatio > 1.85) return false;

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return false;
  const sampleWidth = Math.min(320, canvas.width);
  const sampleHeight = Math.max(
    1,
    Math.round(sampleWidth / aspectRatio),
  );
  const sample = document.createElement("canvas");
  sample.width = sampleWidth;
  sample.height = sampleHeight;
  const sampleContext = sample.getContext("2d", { willReadFrequently: true });
  if (!sampleContext) return false;
  sampleContext.drawImage(canvas, 0, 0, sampleWidth, sampleHeight);
  const pixels = sampleContext.getImageData(
    0,
    0,
    sampleWidth,
    sampleHeight,
  ).data;
  return isGenericCorrectionContentSafe(
    pixels,
    sampleWidth,
    sampleHeight,
    pageSide,
  );
}

function isGenericCorrectionContentSafe(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  pageSide: PassportPageSide,
): boolean {
  const gray = toGrayscale(pixels, width, height);
  const overall = genericRegionQuality(gray, width, height, {
    left: 0.03,
    top: 0.04,
    right: 0.97,
    bottom: 0.96,
  });
  if (overall.contrast < 9 || overall.detailDensity < 0.007) return false;

  const regions = pageSide === "front"
    ? [
        { left: 0.34, top: 0.08, right: 0.97, bottom: 0.70 },
        { left: 0.04, top: 0.66, right: 0.97, bottom: 0.96 },
        { left: 0.03, top: 0.08, right: 0.38, bottom: 0.70 },
      ]
    : [
        { left: 0.10, top: 0.12, right: 0.90, bottom: 0.66 },
        { left: 0.08, top: 0.55, right: 0.92, bottom: 0.92 },
      ];
  const usefulRegions = regions.filter((region) => {
    const quality = genericRegionQuality(gray, width, height, region);
    return quality.contrast >= 7.5 && quality.detailDensity >= 0.006;
  }).length;
  return usefulRegions >= (pageSide === "front" ? 2 : 1);
}

function genericRegionQuality(
  gray: Uint8Array,
  width: number,
  height: number,
  region: {
    left: number;
    top: number;
    right: number;
    bottom: number;
  },
) {
  const left = Math.max(1, Math.round(region.left * (width - 1)));
  const right = Math.min(
    width - 2,
    Math.round(region.right * (width - 1)),
  );
  const top = Math.max(1, Math.round(region.top * (height - 1)));
  const bottom = Math.min(
    height - 2,
    Math.round(region.bottom * (height - 1)),
  );
  let samples = 0;
  let total = 0;
  let squaredTotal = 0;
  let detailed = 0;
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const index = y * width + x;
      const luminance = gray[index];
      samples += 1;
      total += luminance;
      squaredTotal += luminance * luminance;
      if (
        Math.abs(gray[index + 1] - gray[index - 1])
          + Math.abs(gray[index + width] - gray[index - width])
        >= 28
      ) {
        detailed += 1;
      }
    }
  }
  const mean = total / Math.max(1, samples);
  return {
    contrast: Math.sqrt(Math.max(
      0,
      squaredTotal / Math.max(1, samples) - mean * mean,
    )),
    detailDensity: detailed / Math.max(1, samples),
  };
}
