import { rotatedImageBounds } from "./passport-image-crop-geometry";

export const MIN_IMAGE_PREVIEW_ZOOM = 1;
export const MAX_IMAGE_PREVIEW_ZOOM = 3;

export interface ImagePreviewViewport {
  imageWidth: number;
  imageHeight: number;
  viewportWidth: number;
  viewportHeight: number;
  rotationDegrees: number;
  zoom?: number;
}

export interface ImagePreviewSize {
  width: number;
  height: number;
  fitScale: number;
  scale: number;
  zoom: number;
}

/** Display sizing only: crop coordinates and the full-resolution canvas stay unchanged. */
export function fitImagePreview({
  imageWidth,
  imageHeight,
  viewportWidth,
  viewportHeight,
  rotationDegrees,
  zoom = MIN_IMAGE_PREVIEW_ZOOM,
}: ImagePreviewViewport): ImagePreviewSize {
  if (![imageWidth, imageHeight, viewportWidth, viewportHeight].every(
    (dimension) => Number.isFinite(dimension) && dimension > 0,
  )) {
    return { width: 0, height: 0, fitScale: 0, scale: 0, zoom: 1 };
  }

  const bounds = rotatedImageBounds(imageWidth, imageHeight, rotationDegrees);
  const fitScale = Math.min(
    1,
    viewportWidth / bounds.width,
    viewportHeight / bounds.height,
  );
  const requestedZoom = Number.isFinite(zoom)
    ? Math.min(MAX_IMAGE_PREVIEW_ZOOM, Math.max(MIN_IMAGE_PREVIEW_ZOOM, zoom))
    : MIN_IMAGE_PREVIEW_ZOOM;
  const scale = Math.min(1, fitScale * requestedZoom);

  return {
    width: bounds.width * scale,
    height: bounds.height * scale,
    fitScale,
    scale,
    // Return the effective zoom so the toolbar never claims detail beyond native size.
    zoom: scale / fitScale,
  };
}
