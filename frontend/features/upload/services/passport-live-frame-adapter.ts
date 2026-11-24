import type { VideoCrop } from "./passport-live.types.ts";
import { GUIDE_CONTEXT_MARGIN_RATIO } from "./passport-live-policy.ts";

/**
 * Copies the camera pixels visible around the DOM guide. The video uses
 * object-cover, so this conversion keeps edge checks aligned on portrait
 * phones instead of assuming raw camera and viewport coordinates match.
 */
export function drawGuideFrame(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  guide: HTMLElement | null,
  destinationWidth: number,
  destinationHeight: number,
): boolean {
  if (
    video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
    || !video.videoWidth
    || !video.videoHeight
    || destinationWidth < 1
    || destinationHeight < 1
  ) {
    return false;
  }

  const crop = getGuideVideoCrop(video, guide);
  canvas.width = destinationWidth;
  canvas.height = destinationHeight;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return false;
  context.drawImage(
    video,
    crop.left,
    crop.top,
    crop.width,
    crop.height,
    0,
    0,
    destinationWidth,
    destinationHeight,
  );
  return true;
}

function getGuideVideoCrop(
  video: HTMLVideoElement,
  guide: HTMLElement | null,
): VideoCrop {
  const fallback: VideoCrop = {
    left: 0,
    top: 0,
    width: video.videoWidth,
    height: video.videoHeight,
  };
  if (!guide) return fallback;

  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  if (
    videoRect.width <= 0
    || videoRect.height <= 0
    || guideRect.width <= 0
    || guideRect.height <= 0
  ) {
    return fallback;
  }

  const scale = Math.max(
    videoRect.width / video.videoWidth,
    videoRect.height / video.videoHeight,
  );
  if (!Number.isFinite(scale) || scale <= 0) return fallback;
  const renderedWidth = video.videoWidth * scale;
  const renderedHeight = video.videoHeight * scale;
  const offsetX = (renderedWidth - videoRect.width) / 2;
  const offsetY = (renderedHeight - videoRect.height) / 2;
  const guideCrop: VideoCrop = {
    left: (guideRect.left - videoRect.left + offsetX) / scale,
    top: (guideRect.top - videoRect.top + offsetY) / scale,
    width: guideRect.width / scale,
    height: guideRect.height / scale,
  };
  const horizontalMargin = guideCrop.width * GUIDE_CONTEXT_MARGIN_RATIO;
  const verticalMargin = guideCrop.height * GUIDE_CONTEXT_MARGIN_RATIO;

  return clampVideoCrop(
    {
      left: guideCrop.left - horizontalMargin,
      top: guideCrop.top - verticalMargin,
      width: guideCrop.width + horizontalMargin * 2,
      height: guideCrop.height + verticalMargin * 2,
    },
    video.videoWidth,
    video.videoHeight,
  );
}

function clampVideoCrop(
  crop: VideoCrop,
  maximumWidth: number,
  maximumHeight: number,
): VideoCrop {
  const left = Math.max(0, Math.min(maximumWidth - 1, crop.left));
  const top = Math.max(0, Math.min(maximumHeight - 1, crop.top));
  const right = Math.max(
    left + 1,
    Math.min(maximumWidth, crop.left + crop.width),
  );
  const bottom = Math.max(
    top + 1,
    Math.min(maximumHeight, crop.top + crop.height),
  );
  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
  };
}
