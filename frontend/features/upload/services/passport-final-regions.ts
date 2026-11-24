import { roundMetric } from "./camera-pixel-math.ts";
import type { PassportRegionQuality, NormalizedRegion } from "./passport-final.types.ts";

export function analyzeRegion(
  pixels: Uint8ClampedArray,
  gray: Uint8Array,
  width: number,
  height: number,
  region: NormalizedRegion,
): PassportRegionQuality {
  const bounds = pixelBounds(region, width, height);
  let samples = 0;
  let luminanceTotal = 0;
  let luminanceSquaredTotal = 0;
  let darkPixels = 0;
  let clippedHighlights = 0;
  let edgePixels = 0;
  let laplacianSamples = 0;
  let laplacianTotal = 0;
  let laplacianSquaredTotal = 0;

  for (let y = bounds.top; y <= bounds.bottom; y += 1) {
    for (let x = bounds.left; x <= bounds.right; x += 1) {
      const index = y * width + x;
      const luminance = gray[index];
      samples += 1;
      luminanceTotal += luminance;
      luminanceSquaredTotal += luminance * luminance;
      if (luminance < 34) darkPixels += 1;
      const rgbaOffset = index * 4;
      const channelMinimum = Math.min(
        pixels[rgbaOffset],
        pixels[rgbaOffset + 1],
        pixels[rgbaOffset + 2],
      );
      if (luminance > 244 && channelMinimum > 232) {
        clippedHighlights += 1;
      }
      if (
        x <= bounds.left
        || x >= bounds.right
        || y <= bounds.top
        || y >= bounds.bottom
      ) {
        continue;
      }
      const horizontal = Math.abs(gray[index + 1] - gray[index - 1]);
      const vertical = Math.abs(
        gray[index + width] - gray[index - width],
      );
      if (horizontal + vertical >= 34) edgePixels += 1;
      const laplacian = (
        gray[index - 1]
        + gray[index + 1]
        + gray[index - width]
        + gray[index + width]
        - 4 * luminance
      );
      laplacianSamples += 1;
      laplacianTotal += laplacian;
      laplacianSquaredTotal += laplacian * laplacian;
    }
  }

  const meanLuminance = luminanceTotal / Math.max(1, samples);
  const contrast = Math.sqrt(Math.max(
    0,
    luminanceSquaredTotal / Math.max(1, samples)
      - meanLuminance * meanLuminance,
  ));
  const laplacianMean = laplacianTotal / Math.max(1, laplacianSamples);
  const sharpness = Math.max(
    0,
    laplacianSquaredTotal / Math.max(1, laplacianSamples)
      - laplacianMean * laplacianMean,
  );

  return {
    sharpness: roundMetric(sharpness),
    detailDensity: roundMetric(
      edgePixels / Math.max(1, laplacianSamples),
    ),
    contrast: roundMetric(contrast),
    meanLuminance: roundMetric(meanLuminance),
    darkPixelRatio: roundMetric(darkPixels / Math.max(1, samples)),
    clippedHighlightRatio: roundMetric(
      clippedHighlights / Math.max(1, samples),
    ),
  };
}

function pixelBounds(
  region: NormalizedRegion,
  width: number,
  height: number,
) {
  return {
    left: Math.max(1, Math.round(region.left * (width - 1))),
    top: Math.max(1, Math.round(region.top * (height - 1))),
    right: Math.min(
      width - 2,
      Math.round(region.right * (width - 1)),
    ),
    bottom: Math.min(
      height - 2,
      Math.round(region.bottom * (height - 1)),
    ),
  };
}
