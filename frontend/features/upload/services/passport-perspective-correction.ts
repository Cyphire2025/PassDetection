"use client";

import type { PassportNormalizationResult, PassportCanvasNormalizationResult } from "./passport-normalization.types.ts";
import type { PassportPageSide } from "./passport-camera-guide";
import { detectDocumentQuad } from "./passport-quad-detection.ts";
import { rectifyDocument } from "./passport-perspective-warp.ts";
import { isSafeCorrectedPage } from "./passport-correction-content.ts";
import { canvasToFile, nextAnimationFrame } from "./passport-image-encoding.ts";

export async function normalizePassportFile(
  file: File,
  pageSide: PassportPageSide = "front",
): Promise<PassportNormalizationResult> {
  if (!file.type.startsWith("image/")) {
    return { file, corrected: false };
  }

  let bitmap: ImageBitmap | null = null;
  try {
    bitmap = await createImageBitmap(file);
    if (bitmap.width < 640 || bitmap.height < 440) {
      return { file, corrected: false };
    }

    const source = document.createElement("canvas");
    source.width = bitmap.width;
    source.height = bitmap.height;
    const context = source.getContext("2d");
    if (!context) return { file, corrected: false };
    context.drawImage(bitmap, 0, 0);

    await nextAnimationFrame();
    const detectedQuad = detectDocumentQuad(source);
    if (!detectedQuad) return { file, corrected: false };
    const normalized = rectifyDocument(source, detectedQuad);
    if (
      normalized === source
      || !isSafeCorrectedPage(normalized, pageSide)
    ) {
      return { file, corrected: false };
    }

    return {
      file: await canvasToFile(normalized, file.name),
      corrected: true,
    };
  } catch {
    // File upload is an explicit fallback. If decoding or conservative
    // rectification is unavailable, preserve the original instead of
    // silently returning a damaged crop.
    return { file, corrected: false };
  } finally {
    bitmap?.close();
  }
}

export async function normalizePassportCanvasCapture(
  sourceCanvas: HTMLCanvasElement,
  fileName = "passport-capture.jpg",
  pageSide: PassportPageSide = "front",
): Promise<PassportCanvasNormalizationResult> {
  await nextAnimationFrame();
  const detectedQuad = detectDocumentQuad(sourceCanvas);
  const correctionCandidate = detectedQuad
    ? rectifyDocument(sourceCanvas, detectedQuad)
    : sourceCanvas;
  const corrected = correctionCandidate !== sourceCanvas
    && isSafeCorrectedPage(correctionCandidate, pageSide);
  const normalizedCanvas = corrected ? correctionCandidate : sourceCanvas;
  const file = await canvasToFile(normalizedCanvas, fileName);

  return {
    file,
    corrected,
  };
}

export type { PassportNormalizationResult, PassportCanvasNormalizationResult } from "./passport-normalization.types.ts";
