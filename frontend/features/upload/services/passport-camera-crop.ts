interface CropBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function getVisibleGuideCrop(video: HTMLVideoElement, guide: HTMLDivElement | null): CropBounds {
  const videoWidth = video.videoWidth;
  const videoHeight = video.videoHeight;

  if (!guide || videoWidth <= 0 || videoHeight <= 0) {
    return {
      left: 0,
      top: 0,
      width: videoWidth || 1,
      height: videoHeight || 1,
    };
  }

  const videoRect = video.getBoundingClientRect();
  const guideRect = guide.getBoundingClientRect();
  const scale = Math.max(videoRect.width / videoWidth, videoRect.height / videoHeight);
  const renderedWidth = videoWidth * scale;
  const renderedHeight = videoHeight * scale;
  const offsetX = (renderedWidth - videoRect.width) / 2;
  const offsetY = (renderedHeight - videoRect.height) / 2;

  const crop = {
    left: (guideRect.left - videoRect.left + offsetX) / scale,
    top: (guideRect.top - videoRect.top + offsetY) / scale,
    width: guideRect.width / scale,
    height: guideRect.height / scale,
  };

  return clampCrop(crop, videoWidth, videoHeight);
}

function clampCrop(crop: CropBounds, maxWidth: number, maxHeight: number): CropBounds {
  const left = Math.max(0, Math.min(maxWidth - 1, crop.left));
  const top = Math.max(0, Math.min(maxHeight - 1, crop.top));
  const right = Math.max(left + 1, Math.min(maxWidth, crop.left + crop.width));
  const bottom = Math.max(top + 1, Math.min(maxHeight, crop.top + crop.height));

  return {
    left,
    top,
    width: right - left,
    height: bottom - top,
  };
}

export function addCaptureMargin(crop: CropBounds, maxWidth: number, maxHeight: number): CropBounds {
  const horizontalMargin = crop.width * 0.01;
  const verticalMargin = crop.height * 0.01;
  return clampCrop(
    {
      left: crop.left - horizontalMargin,
      top: crop.top - verticalMargin,
      width: crop.width + horizontalMargin * 2,
      height: crop.height + verticalMargin * 2,
    },
    maxWidth,
    maxHeight,
  );
}

