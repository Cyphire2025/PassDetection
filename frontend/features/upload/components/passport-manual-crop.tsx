"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Check,
  Crop as CropIcon,
  Loader2,
  RotateCw,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  resizeCrop,
  rotateCropClockwise,
  type CropDragMode,
} from "@/features/passports/utils/passport-image-crop-geometry";
import {
  createCroppedPassportFile,
  drawPassportCropPreview,
  FULL_PASSPORT_CROP,
  type PassportManualCrop,
} from "../services/passport-manual-crop";
import {
  validatePassportFinalFile,
  type PassportFinalQualityResult,
} from "../services/passport-final-quality";

interface PassportManualCropProps {
  file: File;
  pageSide: "front" | "back";
  source: "camera" | "file";
  onConfirm: (file: File, manuallyCropped: boolean) => void;
  onCancel: () => void;
}

export function PassportManualCrop({
  file,
  pageSide,
  source,
  onConfirm,
  onCancel,
}: PassportManualCropProps) {
  const [sourceObjectUrl] = useState(() => URL.createObjectURL(file));
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [crop, setCrop] = useState<PassportManualCrop>(FULL_PASSPORT_CROP);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [preparedCroppedFile, setPreparedCroppedFile] = useState<File | null>(null);
  const [finalQuality, setFinalQuality] = useState<PassportFinalQualityResult | null>(null);
  const [borderlineConfirmed, setBorderlineConfirmed] = useState(false);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const onCancelRef = useRef(onCancel);
  const processingRef = useRef(false);
  const dragRef = useRef<{
    mode: CropDragMode;
    pointerId: number;
    startX: number;
    startY: number;
    startCrop: PassportManualCrop;
  } | null>(null);

  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    processingRef.current = isProcessing;
  }, [isProcessing]);

  useEffect(() => {
    return () => {
      URL.revokeObjectURL(sourceObjectUrl);
    };
  }, [sourceObjectUrl]);

  useEffect(() => {
    const image = new window.Image();
    image.decoding = "async";
    image.onload = () => {
      setPreviewUnavailable(false);
      imageRef.current = image;
      try {
        if (!canvasRef.current) {
          throw new Error("The crop preview could not be prepared.");
        }
        drawPassportCropPreview(canvasRef.current, image, 0);
        setImageSize({
          width: image.naturalWidth,
          height: image.naturalHeight,
        });
      } catch (previewError) {
        setError(
          previewError instanceof Error
            ? previewError.message
            : "The crop preview could not be displayed.",
        );
      }
    };
    image.onerror = () => {
      imageRef.current = null;
      setPreviewUnavailable(true);
      setError(
        "Manual cropping is not available for this photo format in your browser. You can use the original photo, or choose a JPG, PNG, or WebP image to crop it here.",
      );
    };
    image.src = sourceObjectUrl;
    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [sourceObjectUrl]);

  const redrawPreview = (nextCrop: PassportManualCrop) => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (!canvas || !image) return false;
    try {
      drawPassportCropPreview(canvas, image, nextCrop.rotation_degrees);
      return true;
    } catch (previewError) {
      setError(
        previewError instanceof Error
          ? previewError.message
          : "The crop preview could not be displayed.",
      );
      return false;
    }
  };

  const invalidatePreparedCrop = () => {
    if (!preparedCroppedFile && !finalQuality && !error) return;
    setPreparedCroppedFile(null);
    setFinalQuality(null);
    setBorderlineConfirmed(false);
    setError(null);
  };

  const rotateImage = () => {
    const nextCrop = rotateCropClockwise(crop);
    if (redrawPreview(nextCrop)) {
      invalidatePreparedCrop();
      setCrop(nextCrop);
    }
  };

  const resetCrop = () => {
    if (redrawPreview(FULL_PASSPORT_CROP)) {
      invalidatePreparedCrop();
      setCrop(FULL_PASSPORT_CROP);
    }
  };

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !processingRef.current) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialogRef.current?.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyboard);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyboard);
      document.body.style.overflow = priorOverflow;
      previouslyFocused?.focus();
    };
  }, []);

  const beginPointerDrag = (
    event: ReactPointerEvent<HTMLElement>,
    mode: CropDragMode,
  ) => {
    if (isProcessing) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      mode,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startCrop: crop,
    };
  };

  const movePointerDrag = (event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    const stage = stageRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !stage) return;
    const bounds = stage.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    event.preventDefault();
    invalidatePreparedCrop();
    setCrop(resizeCrop(
      drag.startCrop,
      drag.mode,
      (event.clientX - drag.startX) / bounds.width,
      (event.clientY - drag.startY) / bounds.height,
    ));
  };

  const endPointerDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null;
    }
  };

  const handleCropKeyboard = (
    event: ReactKeyboardEvent<HTMLElement>,
    mode: CropDragMode,
  ) => {
    const delta = keyboardCropDelta(event.key, event.shiftKey ? 0.05 : 0.01);
    if (!delta) return;
    event.preventDefault();
    invalidatePreparedCrop();
    setCrop((current) => resizeCrop(
      current,
      mode,
      delta.x,
      delta.y,
    ));
  };

  const confirmCrop = async () => {
    const image = imageRef.current;
    if (!image || isProcessing) return;
    if (
      preparedCroppedFile
      && finalQuality?.outcome === "borderline"
      && borderlineConfirmed
    ) {
      onConfirm(preparedCroppedFile, true);
      return;
    }
    setIsProcessing(true);
    setError(null);
    try {
      const croppedFile = await createCroppedPassportFile(file, image, crop);
      const quality = await validatePassportFinalFile(croppedFile, pageSide);
      setFinalQuality(quality);
      if (quality.outcome === "hard_failure") {
        setPreparedCroppedFile(null);
        setError(quality.message);
        setIsProcessing(false);
        return;
      }
      if (quality.outcome === "borderline") {
        setPreparedCroppedFile(croppedFile);
        setBorderlineConfirmed(false);
        setIsProcessing(false);
        return;
      }
      onConfirm(croppedFile, true);
    } catch (cropError) {
      setError(
        cropError instanceof Error
          ? cropError.message
          : "The cropped passport image could not be prepared. Please try again.",
      );
      setIsProcessing(false);
    }
  };

  const acceptOriginalPhoto = () => {
    if (isProcessing) return;
    // Some browsers cannot decode HEIC/HEIF, AVIF, TIFF, or BMP locally even
    // though the upload service safely validates and converts those formats.
    // Preserve that established server-side path instead of trapping the user
    // in a crop screen their browser cannot render.
    onConfirm(file, false);
  };

  const label = `Passport ${pageSide === "front" ? "Front" : "Back"}`;
  const imageReady = imageSize.width > 0;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-manual-crop-title"
      aria-describedby="passport-manual-crop-guidance"
      className="fixed inset-0 z-50 flex min-h-[100dvh] flex-col overflow-hidden bg-slate-100 text-slate-950"
    >
      <header className="z-20 flex min-h-16 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] shadow-sm sm:px-6">
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onCancel}
          disabled={isProcessing}
          aria-label="Go back without using this crop"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:bg-slate-100 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
        <div className="min-w-0 text-center">
          <p className="truncate text-xs font-semibold uppercase tracking-wide text-blue-600">
            {label}
          </p>
          <h2
            id="passport-manual-crop-title"
            className="truncate text-lg font-bold tracking-tight"
          >
            Crop passport image
          </h2>
        </div>
        <div className="w-11" aria-hidden="true" />
      </header>

      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-3 p-3 sm:gap-4 sm:p-5">
          <div
            id="passport-manual-crop-guidance"
            className="flex items-start gap-3 rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-5 text-blue-950"
          >
            <CropIcon className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" aria-hidden="true" />
            <div>
              <p className="font-semibold">
                Crop out fingers and surrounding background.
              </p>
              <p className="mt-0.5 text-blue-900">
                Keep the entire passport page, all four corners, and every detail clearly visible.
              </p>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-5 text-red-800"
            >
              {error}
              {previewUnavailable && (
                <p className="mt-1 font-medium">
                  The original will still be checked and converted securely before it is saved.
                </p>
              )}
            </div>
          )}

          {finalQuality?.outcome === "borderline" && (
            <div
              role="status"
              className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm leading-5 text-amber-950"
            >
              <p className="font-semibold">{finalQuality.message}</p>
              <label className="mt-2 flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  checked={borderlineConfirmed}
                  onChange={(event) => setBorderlineConfirmed(event.target.checked)}
                  className="mt-0.5 h-5 w-5 rounded border-amber-400 text-blue-600 focus:ring-blue-600"
                />
                <span>
                  {finalQuality.confirmationPrompt
                    ?? "I checked that the full passport page and all details are readable."}
                </span>
              </label>
            </div>
          )}

          <div className="relative flex min-h-[16rem] flex-1 items-center justify-center overflow-auto rounded-2xl border border-slate-200 bg-slate-950 p-3 shadow-inner sm:p-5">
            {!imageReady && (
              <div role="status" className="flex items-center gap-2 text-sm text-white">
                {!error && (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
                    Loading passport image
                  </>
                )}
              </div>
            )}
            <div
              ref={stageRef}
              className={`${imageReady ? "relative inline-block" : "hidden"} max-w-full select-none overflow-visible bg-black shadow-2xl`}
            >
              <canvas
                ref={canvasRef}
                aria-label={`Crop preview for passport ${pageSide} page`}
                className="block max-h-[52dvh] max-w-full"
              />
              <CropShade crop={crop} />
              <div
                role="group"
                tabIndex={0}
                aria-label="Crop frame. Drag to move it, or use arrow keys. Hold Shift for larger keyboard steps."
                className="absolute cursor-move touch-none border-2 border-white shadow-[0_0_0_1px_rgba(15,23,42,0.9)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                style={cropStyle(crop)}
                onPointerDown={(event) => beginPointerDrag(event, "move")}
                onPointerMove={movePointerDrag}
                onPointerUp={endPointerDrag}
                onPointerCancel={endPointerDrag}
                onKeyDown={(event) => handleCropKeyboard(event, "move")}
              >
                {(["nw", "ne", "sw", "se"] as const).map((corner) => (
                  <button
                    key={corner}
                    type="button"
                    aria-label={`Resize crop from ${cornerLabel(corner)} corner`}
                    className={`absolute flex h-11 w-11 touch-none items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${cornerClassName(corner)}`}
                    onPointerDown={(event) => beginPointerDrag(event, corner)}
                    onPointerMove={movePointerDrag}
                    onPointerUp={endPointerDrag}
                    onPointerCancel={endPointerDrag}
                    onKeyDown={(event) => handleCropKeyboard(event, corner)}
                  >
                    <span className="h-5 w-5 rounded-full border-2 border-slate-900 bg-white shadow-md" aria-hidden="true" />
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <p>Drag the white frame and its corner handles to adjust the crop.</p>
            <p className="font-medium text-slate-600">
              {source === "camera" ? "Captured with live camera" : "Selected from this device"}
            </p>
          </div>
        </div>
      </main>

      <footer className="z-20 border-t border-slate-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-6px_18px_rgba(15,23,42,0.08)] sm:px-6 sm:py-4">
        <div className="mx-auto grid w-full max-w-5xl gap-2 sm:grid-cols-[auto_auto_1fr_auto] sm:items-center">
          <Button
            type="button"
            variant="outline"
            className="h-11"
            disabled={isProcessing || !imageReady}
            onClick={rotateImage}
          >
            <RotateCw className="h-4 w-4" aria-hidden="true" />
            Rotate 90°
          </Button>
          <Button
            type="button"
            variant="secondary"
            className="h-11"
            disabled={isProcessing || !imageReady}
            onClick={resetCrop}
          >
            Reset crop
          </Button>
          <div aria-hidden="true" />
          <div className="grid gap-2 min-[380px]:grid-cols-2">
            <Button
              type="button"
              variant="outline"
              className="h-11"
              disabled={isProcessing}
              onClick={onCancel}
            >
              {source === "camera" ? "Retake photo" : "Choose another"}
            </Button>
            <Button
              type="button"
              className="h-11 bg-blue-600 font-semibold text-white hover:bg-blue-700"
              disabled={
                isProcessing
                || (!imageReady && !previewUnavailable)
                || (finalQuality?.outcome === "borderline" && !borderlineConfirmed)
              }
              aria-busy={isProcessing}
              onClick={() => {
                if (previewUnavailable) {
                  acceptOriginalPhoto();
                  return;
                }
                void confirmCrop();
              }}
            >
              {isProcessing
                ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                : <Check className="h-4 w-4" aria-hidden="true" />}
              {isProcessing
                ? "Checking crop"
                : previewUnavailable
                  ? "Use original photo"
                : finalQuality?.outcome === "borderline"
                  ? "Confirm cropped photo"
                  : "Use cropped photo"}
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}

function CropShade({ crop }: { crop: PassportManualCrop }) {
  const right = crop.x + crop.width;
  const bottom = crop.y + crop.height;
  const shared = "pointer-events-none absolute bg-slate-950/65";
  return (
    <>
      <div className={shared} style={{ inset: `0 0 ${percent(1 - crop.y)} 0` }} />
      <div className={shared} style={{ inset: `${percent(bottom)} 0 0 0` }} />
      <div
        className={shared}
        style={{
          inset: `${percent(crop.y)} ${percent(1 - crop.x)} ${percent(1 - bottom)} 0`,
        }}
      />
      <div
        className={shared}
        style={{
          inset: `${percent(crop.y)} 0 ${percent(1 - bottom)} ${percent(right)}`,
        }}
      />
    </>
  );
}

function cropStyle(crop: PassportManualCrop) {
  return {
    left: percent(crop.x),
    top: percent(crop.y),
    width: percent(crop.width),
    height: percent(crop.height),
  };
}

function keyboardCropDelta(key: string, step: number) {
  if (key === "ArrowLeft") return { x: -step, y: 0 };
  if (key === "ArrowRight") return { x: step, y: 0 };
  if (key === "ArrowUp") return { x: 0, y: -step };
  if (key === "ArrowDown") return { x: 0, y: step };
  return null;
}

function cornerClassName(corner: Exclude<CropDragMode, "move">) {
  const vertical = corner.startsWith("n") ? "-top-2" : "-bottom-2";
  const horizontal = corner.endsWith("w") ? "-left-2" : "-right-2";
  return `${vertical} ${horizontal}`;
}

function cornerLabel(corner: Exclude<CropDragMode, "move">) {
  return ({
    nw: "top left",
    ne: "top right",
    sw: "bottom left",
    se: "bottom right",
  })[corner];
}

function percent(value: number) {
  return `${value * 100}%`;
}
