"use client";

/**
 * Passport images are identity documents.  Do not geometrically transform
 * them in the browser: perspective warps and auto-rotation can subtly change
 * the appearance of the document and make a perfectly usable Visa image look
 * artificial.  The scanner's job is to gate a good capture, not to recreate it.
 */
export interface PassportNormalizationResult {
  file: File;
  previewDataUrl: string;
  corrected: boolean;
}

export async function normalizePassportFile(file: File): Promise<PassportNormalizationResult> {
  return {
    file,
    previewDataUrl: await fileToDataUrl(file),
    corrected: false,
  };
}

/**
 * Captures the pixels selected by the guide exactly as drawn.  No crop-edge
 * fitting, perspective warp, rotation, or resampling is applied.
 */
export async function normalizePassportCanvasCapture(
  sourceCanvas: HTMLCanvasElement,
  fileName = "passport-capture.jpg",
): Promise<PassportNormalizationResult> {
  const file = await canvasToFile(sourceCanvas, fileName);
  return {
    file,
    previewDataUrl: sourceCanvas.toDataURL("image/jpeg", 0.95),
    corrected: false,
  };
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to prepare passport preview"));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(file);
  });
}

async function canvasToFile(canvas: HTMLCanvasElement, fileName: string): Promise<File> {
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((createdBlob) => {
      if (!createdBlob) {
        reject(new Error("Failed to create passport image"));
        return;
      }
      resolve(createdBlob);
    }, "image/jpeg", 0.95);
  });

  return new File([blob], fileName.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
}
