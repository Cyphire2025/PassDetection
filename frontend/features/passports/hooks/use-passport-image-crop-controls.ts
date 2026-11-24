"use client";

import { useRef, type Dispatch, type KeyboardEvent, type MutableRefObject, type PointerEvent, type SetStateAction } from "react";
import type { PassportImageCropRect } from "../api/passports.api";
import { resizeCrop, type CropDragMode } from "../utils/passport-image-crop-geometry";
import { keyboardDelta } from "../utils/passport-image-editor-state";

export function usePassportImageCropControls(cropRect: PassportImageCropRect,
  setCropRect: Dispatch<SetStateAction<PassportImageCropRect>>, busyRef: MutableRefObject<boolean>) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    mode: CropDragMode; pointerId: number; startX: number; startY: number; startCrop: PassportImageCropRect;
  } | null>(null);

  const beginPointerDrag = (event: PointerEvent<HTMLElement>, mode: CropDragMode) => {
    if (busyRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { mode, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, startCrop: cropRect };
  };

  const movePointerDrag = (event: PointerEvent<HTMLElement>) => {
    if (busyRef.current) return;
    const drag = dragRef.current;
    const stage = stageRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !stage) return;
    const bounds = stage.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    event.preventDefault();
    setCropRect(resizeCrop(drag.startCrop, drag.mode,
      (event.clientX - drag.startX) / bounds.width, (event.clientY - drag.startY) / bounds.height));
  };

  const endPointerDrag = (event: PointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
  };

  const handleKeyboard = (event: KeyboardEvent<HTMLElement>, mode: CropDragMode) => {
    if (busyRef.current) return;
    const delta = keyboardDelta(event.key, event.shiftKey ? 0.05 : 0.01);
    if (!delta) return;
    event.preventDefault();
    event.stopPropagation();
    setCropRect((current) => resizeCrop(current, mode, delta.x, delta.y));
  };

  return { stageRef, beginPointerDrag, movePointerDrag, endPointerDrag, handleKeyboard };
}
