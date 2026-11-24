"use client";

import {
  useEffect, useRef, useState,
  type MutableRefObject, type Dispatch, type SetStateAction,
} from "react";
import type { PassportImageCropRect, PassportImageCropState } from "../api/passports.api";
import {
  fineRotationOffset, MAX_FINE_ROTATION, MIN_FINE_ROTATION,
  normalizeCrop, normalizeRotationDegrees, rotateCropClockwise,
} from "../utils/passport-image-crop-geometry";
import { FULL_IMAGE_CROP, clampSharpness } from "../utils/passport-image-editor-state";
import { drawEditedImage } from "../utils/passport-image-editor-preview";
import { usePassportImageCropControls } from "./use-passport-image-crop-controls";

export function usePassportImageEditorDraft(
  metadata: PassportImageCropState | null,
  sourceObjectUrl: string | null,
  activePanel: string,
  busyRef: MutableRefObject<boolean>,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  const [draft, setDraft] = useState(() => initialDraft(metadata));
  if (draft.metadata !== metadata) setDraft(initialDraft(metadata));
  const { cropRect, fineRotation, sharpness } = draft;
  const setCropRect: Dispatch<SetStateAction<PassportImageCropRect>> = (update) => setDraft((current) => ({
    ...current, cropRect: typeof update === "function" ? update(current.cropRect) : update,
  }));
  const setSharpness: Dispatch<SetStateAction<number>> = (update) => setDraft((current) => ({
    ...current, sharpness: typeof update === "function" ? update(current.sharpness) : update,
  }));
  const [isFineRotating, setIsFineRotating] = useState(false);
  const [previewDimension, setPreviewDimension] = useState(1200);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const workingImageRef = useRef<HTMLImageElement | null>(null);
  const gestures = usePassportImageCropControls(cropRect, setCropRect, busyRef);

  const workingObjectUrl = sourceObjectUrl;

  useEffect(() => {
    if (!workingObjectUrl) return;
    const image = new window.Image();
    workingImageRef.current = null;
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    image.onload = () => {
      workingImageRef.current = image;
      setImageSize({
        width: image.naturalWidth,
        height: image.naturalHeight,
      });
    };
    image.onerror = () => setError("The image could not be displayed.");
    image.src = workingObjectUrl;
    return () => {
      if (workingImageRef.current === image) workingImageRef.current = null;
      image.onload = null;
      image.onerror = null;
    };
  }, [workingObjectUrl, setError]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const image = workingImageRef.current;
    if (!canvas || !image || !workingObjectUrl || imageSize.width === 0) return;
    const animationFrame = window.requestAnimationFrame(() => {
      drawEditedImage(
        canvas,
        image,
        cropRect.rotation_degrees,
        isFineRotating ? 1 : sharpness,
        isFineRotating,
        previewDimension,
      );
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [
    activePanel,
    cropRect.rotation_degrees,
    imageSize.width,
    isFineRotating,
    previewDimension,
    sharpness,
    workingObjectUrl,
  ]);

  const updateFineRotation = (value: number) => {
    const nextFineRotation = Math.min(
      MAX_FINE_ROTATION,
      Math.max(MIN_FINE_ROTATION, Math.round(value)),
    );
    setDraft((current) => ({
      ...current,
      fineRotation: nextFineRotation,
      cropRect: normalizeCrop({ ...current.cropRect,
        rotation_degrees: normalizeRotationDegrees(current.rotationBase + nextFineRotation),
      }),
    }));
  };

  const rotate = (direction: "left" | "right") => {
    const turns = direction === "right" ? 1 : 3;
    setDraft((current) => {
      let next = current.cropRect;
      for (let turn = 0; turn < turns; turn += 1) next = rotateCropClockwise(next);
      return { ...current, rotationBase: normalizeRotationDegrees(current.rotationBase + turns * 90), cropRect: next };
    });
  };

  const undoChanges = () => {
    setDraft(initialDraft(metadata));
  };

  const savedCrop = normalizeCrop(metadata?.crop ?? FULL_IMAGE_CROP);
  const hasChanges = sharpness !== clampSharpness(metadata?.sharpness ?? 1)
    || (Object.keys(savedCrop) as (keyof PassportImageCropRect)[]).some(key => cropRect[key] !== savedCrop[key]);
  return {
    ...gestures,
    cropRect,
    setCropRect,
    fineRotation,
    setIsFineRotating,
    sharpness,
    setSharpness,
    setPreviewDimension,
    imageSize,
    canvasRef,
    updateFineRotation,
    rotate,
    undoChanges,
    hasChanges,
  };
}

function initialDraft(metadata: PassportImageCropState | null) {
  const cropRect = normalizeCrop(metadata?.crop ?? FULL_IMAGE_CROP);
  const fineRotation = fineRotationOffset(cropRect.rotation_degrees);
  return { metadata, cropRect, fineRotation, sharpness: clampSharpness(metadata?.sharpness ?? 1),
    rotationBase: normalizeRotationDegrees(cropRect.rotation_degrees - fineRotation) };
}
