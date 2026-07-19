export interface CameraCropBounds {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface CapturedCameraSource {
  image: CanvasImageSource;
  width: number;
  height: number;
  mode: "image_capture" | "video_frame";
  close: () => void;
}

/**
 * Prefer the MediaStream Image Capture API for a sensor-quality still. Browsers
 * and in-app webviews implement this API inconsistently, so every failure
 * returns to the already-playing highest-resolution video frame.
 */
export async function captureBestCameraSource(
  video: HTMLVideoElement,
  stream: MediaStream | null,
): Promise<CapturedCameraSource> {
  const fallback = videoFrameSource(video);
  const track = stream?.getVideoTracks()[0];
  if (
    !track
    || track.readyState !== "live"
    || typeof ImageCapture !== "function"
    || typeof createImageBitmap !== "function"
  ) {
    return fallback;
  }

  try {
    const imageCapture = new ImageCapture(track);
    const settings = await preferredPhotoSettings(imageCapture);
    let blob: Blob;
    try {
      blob = settings
        ? await imageCapture.takePhoto(settings)
        : await imageCapture.takePhoto();
    } catch {
      if (!settings) throw new Error("ImageCapture.takePhoto failed");
      blob = await imageCapture.takePhoto();
    }
    if (!blob.size) return fallback;
    const bitmap = await createImageBitmap(blob);
    if (bitmap.width < 1 || bitmap.height < 1) {
      bitmap.close();
      return fallback;
    }
    return {
      image: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      mode: "image_capture",
      close: () => bitmap.close(),
    };
  } catch {
    return fallback;
  }
}

/**
 * Maps a crop measured in the live video frame onto a still image. Sensor
 * photos can use a different aspect ratio from the preview; the centred source
 * window models the preview crop without stretching either image.
 */
export function remapVideoCropToSource(
  crop: CameraCropBounds,
  videoWidth: number,
  videoHeight: number,
  sourceWidth: number,
  sourceHeight: number,
): CameraCropBounds {
  if (
    videoWidth <= 0
    || videoHeight <= 0
    || sourceWidth <= 0
    || sourceHeight <= 0
  ) {
    return {
      left: 0,
      top: 0,
      width: Math.max(1, sourceWidth),
      height: Math.max(1, sourceHeight),
    };
  }

  const boundedCrop = clampCrop(crop, videoWidth, videoHeight);
  const videoAspectRatio = videoWidth / videoHeight;
  const sourceAspectRatio = sourceWidth / sourceHeight;
  let sourceWindowLeft = 0;
  let sourceWindowTop = 0;
  let sourceWindowWidth = sourceWidth;
  let sourceWindowHeight = sourceHeight;

  if (sourceAspectRatio > videoAspectRatio) {
    sourceWindowWidth = sourceHeight * videoAspectRatio;
    sourceWindowLeft = (sourceWidth - sourceWindowWidth) / 2;
  } else if (sourceAspectRatio < videoAspectRatio) {
    sourceWindowHeight = sourceWidth / videoAspectRatio;
    sourceWindowTop = (sourceHeight - sourceWindowHeight) / 2;
  }

  return clampCrop(
    {
      left: sourceWindowLeft
        + (boundedCrop.left / videoWidth) * sourceWindowWidth,
      top: sourceWindowTop
        + (boundedCrop.top / videoHeight) * sourceWindowHeight,
      width: (boundedCrop.width / videoWidth) * sourceWindowWidth,
      height: (boundedCrop.height / videoHeight) * sourceWindowHeight,
    },
    sourceWidth,
    sourceHeight,
  );
}

async function preferredPhotoSettings(
  imageCapture: ImageCapture,
): Promise<PhotoSettings | undefined> {
  try {
    const capabilities = await imageCapture.getPhotoCapabilities();
    const imageWidth = capabilities.imageWidth?.max;
    const imageHeight = capabilities.imageHeight?.max;
    if (
      Number.isFinite(imageWidth)
      && Number.isFinite(imageHeight)
      && imageWidth
      && imageHeight
    ) {
      return { imageWidth, imageHeight };
    }
  } catch {
    // Capability queries are optional; takePhoto() can still work without one.
  }
  return undefined;
}

function videoFrameSource(video: HTMLVideoElement): CapturedCameraSource {
  if (video.videoWidth < 1 || video.videoHeight < 1) {
    throw new Error("The camera frame is not ready.");
  }
  return {
    image: video,
    width: video.videoWidth,
    height: video.videoHeight,
    mode: "video_frame",
    close: () => undefined,
  };
}

function clampCrop(
  crop: CameraCropBounds,
  maximumWidth: number,
  maximumHeight: number,
): CameraCropBounds {
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
