export interface ImagePlacement { x: number; y: number; zoom: number }
export const DEFAULT_IMAGE_PLACEMENT: ImagePlacement = { x: 50, y: 50, zoom: 1 };

export function cropRegion(width: number, height: number, aspect: number, placement: ImagePlacement) {
  const zoom = Math.max(1, Math.min(3, placement.zoom));
  const cropWidth = Math.min(width, height * aspect) / zoom;
  const cropHeight = cropWidth / aspect;
  const left = (width - cropWidth) * Math.max(0, Math.min(100, placement.x)) / 100;
  const top = (height - cropHeight) * Math.max(0, Math.min(100, placement.y)) / 100;
  return { left, top, width: cropWidth, height: cropHeight };
}

export async function cropBrandingImage(source: File | string, aspect: number, placement: ImagePlacement): Promise<File> {
  const blob = typeof source === "string" ? await fetchCurrentImage(source) : source;
  const image = await createImageBitmap(blob);
  try {
    const crop = cropRegion(image.width, image.height, aspect, placement);
    const width = Math.max(1, Math.min(2560, Math.round(crop.width)));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = Math.max(1, Math.round(width / aspect));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Image adjustment is unavailable in this browser.");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, crop.left, crop.top, crop.width, crop.height, 0, 0, canvas.width, canvas.height);
    const cropped = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      (result) => result ? resolve(result) : reject(new Error("The image could not be adjusted.")), "image/jpeg", 0.94,
    ));
    return new File([cropped], "workspace-image.jpg", { type: "image/jpeg" });
  } finally {
    image.close();
  }
}

async function fetchCurrentImage(source: string) {
  const url = new URL(source, window.location.origin);
  if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/v1/branding/")) {
    throw new Error("Choose a workspace image before adjusting it.");
  }
  const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (!response.ok) throw new Error("The current image is unavailable. Reopen the editor or choose another image.");
  return response.blob();
}
