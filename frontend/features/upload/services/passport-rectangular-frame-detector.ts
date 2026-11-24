import type { RectangularPassportFrameResult } from "./passport-live.types.ts";
import { SAMPLE_WIDTH, SAMPLE_HEIGHT } from "./passport-live-policy.ts";
import { drawGuideFrame } from "./passport-live-frame-adapter.ts";
import { analyzeRectangularPassportFramePixels } from "./passport-live-analysis.ts";
import { emptyResult } from "./passport-live-pixels.ts";

/**
 * Lightweight live-camera gate for a complete, near-level physical page.
 *
 * The detector deliberately does not inspect passport layout or MRZ content.
 * It instead requires three strong coherent boundaries plus a plausible fourth
 * boundary, and checks that their quadrilateral fills and aligns with the
 * visible guide. This keeps a weak open-book edge usable without allowing
 * unrelated texture, a partial page, or a rotated page to unlock capture.
 */
export function detectRectangularPassportFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null = null,
): RectangularPassportFrameResult {
  if (!drawGuideFrame(
    video,
    canvas,
    guide,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  )) {
    return emptyResult("checking");
  }

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return emptyResult("checking");
  const { data } = context.getImageData(
    0,
    0,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  );
  return analyzeRectangularPassportFramePixels(
    data,
    SAMPLE_WIDTH,
    SAMPLE_HEIGHT,
  );
}

export { analyzeRectangularPassportFramePixels } from "./passport-live-analysis.ts";
export type { RectangularPassportFrameStatus, RectangularPassportFrameResult } from "./passport-live.types.ts";
