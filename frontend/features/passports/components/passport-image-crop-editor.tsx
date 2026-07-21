"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Crop, Loader2, RotateCw, X } from "lucide-react";
import { Button } from "@/components/ui";
import {
  passportsApi,
  type PassportImageCropRect,
  type PassportImageCropState,
  type PassportImageType,
} from "../api/passports.api";
import {
  normalizeCrop,
  resizeCrop,
  rotateCropClockwise,
  type CropDragMode,
} from "../utils/passport-image-crop-geometry";

interface PassportImageCropEditorProps {
  submissionId: string;
  imageType: PassportImageType;
  label: string;
  returnFocusTarget: HTMLButtonElement;
  onClose: () => void;
  onSaved: () => void;
}

const FULL_IMAGE_CROP: PassportImageCropRect = {
  x: 0,
  y: 0,
  width: 1,
  height: 1,
  rotation_degrees: 0,
};

export function PassportImageCropEditor({
  submissionId,
  imageType,
  label,
  returnFocusTarget,
  onClose,
  onSaved,
}: PassportImageCropEditorProps) {
  const [metadata, setMetadata] = useState<PassportImageCropState | null>(null);
  const [cropRect, setCropRect] = useState<PassportImageCropRect>(FULL_IMAGE_CROP);
  const [originalObjectUrl, setOriginalObjectUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(false);
  const dragRef = useRef<{
    mode: CropDragMode;
    pointerId: number;
    startX: number;
    startY: number;
    startCrop: PassportImageCropRect;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    void Promise.all([
      passportsApi.getImageCrop(submissionId, imageType),
      passportsApi.getOriginalImage(submissionId, imageType, controller.signal),
    ]).then(([state, blob]) => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setMetadata(state);
      setCropRect(normalizeCrop(state.crop ?? FULL_IMAGE_CROP));
      setOriginalObjectUrl(objectUrl);
    }).catch((loadError) => {
      if (!controller.signal.aborted) {
        setError(readCropError(loadError, "Could not load the original image for cropping."));
      }
    });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageType, submissionId]);

  useEffect(() => {
    if (!originalObjectUrl) return;
    const image = new window.Image();
    image.onload = () => setImageSize({
      width: image.naturalWidth,
      height: image.naturalHeight,
    });
    image.onerror = () => setError("The original image could not be displayed.");
    image.src = originalObjectUrl;
    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [originalObjectUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !originalObjectUrl || imageSize.width === 0) return;
    const image = new window.Image();
    image.onload = () => drawRotatedImage(canvas, image, cropRect.rotation_degrees);
    image.src = originalObjectUrl;
    return () => {
      image.onload = null;
    };
  }, [cropRect.rotation_degrees, imageSize.width, originalObjectUrl]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current = isSaving || isResetting;
  }, [isResetting, isSaving]);

  useEffect(() => {
    returnFocusRef.current = returnFocusTarget;
    const handleModalKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleModalKeyboard);
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("keydown", handleModalKeyboard);
      document.body.style.overflow = priorOverflow;
      returnFocusRef.current?.focus();
    };
  }, [returnFocusTarget]);

  const beginPointerDrag = (
    event: ReactPointerEvent<HTMLElement>,
    mode: CropDragMode,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      mode,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startCrop: cropRect,
    };
  };

  const movePointerDrag = (event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    const stage = stageRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !stage) return;
    const bounds = stage.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    event.preventDefault();
    setCropRect(resizeCrop(
      drag.startCrop,
      drag.mode,
      (event.clientX - drag.startX) / bounds.width,
      (event.clientY - drag.startY) / bounds.height,
    ));
  };

  const endPointerDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null;
  };

  const handleKeyboard = (
    event: ReactKeyboardEvent<HTMLElement>,
    mode: CropDragMode,
  ) => {
    const step = event.shiftKey ? 0.05 : 0.01;
    const delta = keyboardDelta(event.key, step);
    if (!delta) return;
    event.preventDefault();
    setCropRect((current) => resizeCrop(current, mode, delta.x, delta.y));
  };

  const rotateClockwise = () => {
    setCropRect((current) => rotateCropClockwise(current));
  };

  const save = async () => {
    if (!metadata || isSaving || isResetting) return;
    setError(null);
    setIsSaving(true);
    try {
      await passportsApi.saveImageCrop(submissionId, imageType, {
        ...cropRect,
        expected_revision: metadata.revision,
      });
      onSaved();
      onClose();
    } catch (saveError) {
      setError(readCropError(saveError, "Could not save this crop. Please try again."));
    } finally {
      setIsSaving(false);
    }
  };

  const reset = async () => {
    if (!metadata || isSaving || isResetting) return;
    setError(null);
    setIsResetting(true);
    try {
      await passportsApi.resetImageCrop(
        submissionId,
        imageType,
        metadata.revision,
      );
      onSaved();
      onClose();
    } catch (resetError) {
      setError(readCropError(resetError, "Could not reset this crop. Please try again."));
    } finally {
      setIsResetting(false);
    }
  };

  const busy = isSaving || isResetting;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/70 p-2 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-crop-title"
    >
      <div ref={dialogRef} className="flex max-h-[96vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-3 sm:px-6 sm:py-4">
          <div>
            <h2 id="passport-crop-title" className="font-semibold text-slate-950">
              Crop {label}
            </h2>
            <p className="mt-1 text-xs text-slate-500 sm:text-sm">
              Drag the clear frame or its corner handles. The dimmed area will be removed.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close crop editor"
            disabled={busy}
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-slate-100 p-3 sm:p-5">
          {error && (
            <div role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {!originalObjectUrl || imageSize.width === 0 ? (
            <div className="flex min-h-80 flex-1 items-center justify-center text-sm text-slate-500" role="status">
              {error ? "Crop editor unavailable" : <><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading original image</>}
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center overflow-auto">
              <div ref={stageRef} className="relative inline-block max-w-full select-none overflow-hidden bg-black shadow-xl">
                <canvas
                  ref={canvasRef}
                  aria-label={`Full original ${label}`}
                  className="block max-h-[58vh] max-w-full"
                />
                <CropShade crop={cropRect} />
                <div
                  role="group"
                  tabIndex={0}
                  aria-label="Crop frame. Use arrow keys to move it; hold Shift for larger steps."
                  className="absolute cursor-move touch-none border-2 border-white shadow-[0_0_0_1px_rgba(15,23,42,0.8)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                  style={cropStyle(cropRect)}
                  onPointerDown={(event) => beginPointerDrag(event, "move")}
                  onPointerMove={movePointerDrag}
                  onPointerUp={endPointerDrag}
                  onPointerCancel={endPointerDrag}
                  onKeyDown={(event) => handleKeyboard(event, "move")}
                >
                  {(["nw", "ne", "sw", "se"] as const).map((corner) => (
                    <button
                      key={corner}
                      type="button"
                      aria-label={`Resize crop from ${cornerLabel(corner)} corner`}
                      className={`absolute h-7 w-7 touch-none rounded-full border-2 border-slate-800 bg-white shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${cornerClassName(corner)}`}
                      onPointerDown={(event) => beginPointerDrag(event, corner)}
                      onPointerMove={movePointerDrag}
                      onPointerUp={endPointerDrag}
                      onPointerCancel={endPointerDrag}
                      onKeyDown={(event) => handleKeyboard(event, corner)}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        <footer className="flex flex-col gap-3 border-t border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:py-4">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" className="gap-2" disabled={busy || !metadata} onClick={rotateClockwise}>
              <RotateCw className="h-4 w-4" /> Rotate 90 degrees
            </Button>
            <Button type="button" variant="secondary" disabled={busy || !metadata?.crop} onClick={() => void reset()}>
              {isResetting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Reset crop
            </Button>
          </div>
          <div className="flex gap-2 sm:justify-end">
            <Button type="button" variant="outline" className="flex-1 sm:flex-none" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="button" className="flex-1 gap-2 sm:flex-none" disabled={busy || !metadata} onClick={() => void save()}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crop className="h-4 w-4" />}
              Save crop
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function CropShade({ crop }: { crop: PassportImageCropRect }) {
  const right = crop.x + crop.width;
  const bottom = crop.y + crop.height;
  const shared = "pointer-events-none absolute bg-slate-950/60";
  return (
    <>
      <div className={shared} style={{ inset: `0 0 ${percent(1 - crop.y)} 0` }} />
      <div className={shared} style={{ inset: `${percent(bottom)} 0 0 0` }} />
      <div className={shared} style={{ inset: `${percent(crop.y)} ${percent(1 - crop.x)} ${percent(1 - bottom)} 0` }} />
      <div className={shared} style={{ inset: `${percent(crop.y)} 0 ${percent(1 - bottom)} ${percent(right)}` }} />
    </>
  );
}

function drawRotatedImage(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  rotation: PassportImageCropRect["rotation_degrees"],
) {
  const swapsAxes = rotation === 90 || rotation === 270;
  const sourceWidth = image.naturalWidth;
  const sourceHeight = image.naturalHeight;
  const rotatedWidth = swapsAxes ? sourceHeight : sourceWidth;
  const rotatedHeight = swapsAxes ? sourceWidth : sourceHeight;
  const scale = Math.min(1, 1600 / Math.max(rotatedWidth, rotatedHeight));
  canvas.width = Math.max(1, Math.round(rotatedWidth * scale));
  canvas.height = Math.max(1, Math.round(rotatedHeight * scale));
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.save();
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate((rotation * Math.PI) / 180);
  context.drawImage(
    image,
    -(sourceWidth * scale) / 2,
    -(sourceHeight * scale) / 2,
    sourceWidth * scale,
    sourceHeight * scale,
  );
  context.restore();
}

function cropStyle(crop: PassportImageCropRect) {
  return {
    left: percent(crop.x),
    top: percent(crop.y),
    width: percent(crop.width),
    height: percent(crop.height),
  };
}

function keyboardDelta(key: string, step: number) {
  if (key === "ArrowLeft") return { x: -step, y: 0 };
  if (key === "ArrowRight") return { x: step, y: 0 };
  if (key === "ArrowUp") return { x: 0, y: -step };
  if (key === "ArrowDown") return { x: 0, y: step };
  return null;
}

function cornerClassName(corner: Exclude<CropDragMode, "move">) {
  const vertical = corner.startsWith("n") ? "-top-3.5" : "-bottom-3.5";
  const horizontal = corner.endsWith("w") ? "-left-3.5" : "-right-3.5";
  return `${vertical} ${horizontal}`;
}

function cornerLabel(corner: Exclude<CropDragMode, "move">) {
  return ({ nw: "top left", ne: "top right", sw: "bottom left", se: "bottom right" })[corner];
}

function percent(value: number) {
  return `${value * 100}%`;
}

function readCropError(error: unknown, fallback: string) {
  if (
    typeof error === "object"
    && error !== null
    && "response" in error
  ) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}
