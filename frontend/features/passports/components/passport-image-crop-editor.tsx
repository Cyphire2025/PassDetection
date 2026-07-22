"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Loader2,
  Pencil,
  RotateCw,
  Save,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
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

interface VisaAiPreviewState {
  blob: Blob;
  objectUrl: string;
  token: string;
  prompt: string;
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
  const isVisaPhoto = imageType === "visa_photo";
  const [metadata, setMetadata] = useState<PassportImageCropState | null>(null);
  const [cropRect, setCropRect] = useState<PassportImageCropRect>(FULL_IMAGE_CROP);
  const [sharpness, setSharpness] = useState(1);
  const [sourceObjectUrl, setSourceObjectUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [activePanel, setActivePanel] = useState<"adjust" | "ai">("adjust");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiPreview, setAiPreview] = useState<VisaAiPreviewState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const aiRequestRef = useRef<AbortController | null>(null);
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
    void passportsApi.getImageCrop(submissionId, imageType)
      .then(async (state) => {
        const blob = await passportsApi.getEditableImage(
          state.editable_source_url,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setMetadata(state);
        setCropRect(normalizeCrop(state.crop ?? FULL_IMAGE_CROP));
        setSharpness(clampSharpness(state.sharpness));
        setSourceObjectUrl(objectUrl);
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) {
          setError(readEditError(loadError, "Could not load this image for editing."));
        }
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageType, submissionId]);

  useEffect(() => {
    return () => {
      if (aiPreview) URL.revokeObjectURL(aiPreview.objectUrl);
    };
  }, [aiPreview]);

  useEffect(() => {
    return () => aiRequestRef.current?.abort();
  }, []);

  const workingObjectUrl = aiPreview?.objectUrl ?? sourceObjectUrl;

  useEffect(() => {
    if (!workingObjectUrl) return;
    const image = new window.Image();
    image.onload = () => setImageSize({
      width: image.naturalWidth,
      height: image.naturalHeight,
    });
    image.onerror = () => setError("The image could not be displayed.");
    image.src = workingObjectUrl;
    return () => {
      image.onload = null;
      image.onerror = null;
    };
  }, [workingObjectUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !workingObjectUrl || imageSize.width === 0) return;
    const image = new window.Image();
    const timer = window.setTimeout(() => {
      image.onload = () => drawEditedImage(
        canvas,
        image,
        cropRect.rotation_degrees,
        sharpness,
      );
      image.src = workingObjectUrl;
    }, 60);
    return () => {
      window.clearTimeout(timer);
      image.onload = null;
    };
  }, [cropRect.rotation_degrees, imageSize.width, sharpness, workingObjectUrl]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current = isSaving || isResetting || isGenerating;
  }, [isGenerating, isResetting, isSaving]);

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
        'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
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

  const updatePrompt = (value: string) => {
    setAiPrompt(value);
    setAiPreview(null);
  };

  const generateAiPreview = async () => {
    const prompt = aiPrompt.trim().split(/\s+/).join(" ");
    if (!metadata || prompt.length < 3 || isGenerating) return;
    setError(null);
    setIsGenerating(true);
    const controller = new AbortController();
    aiRequestRef.current = controller;
    try {
      const generated = await passportsApi.generateVisaAiPreview(
        submissionId,
        prompt,
        controller.signal,
      );
      setAiPreview({
        ...generated,
        objectUrl: URL.createObjectURL(generated.blob),
        prompt,
      });
    } catch (generationError) {
      if (!controller.signal.aborted) {
        setError(readEditError(
          generationError,
          "Could not generate a safe Visa photo preview.",
        ));
      }
    } finally {
      if (aiRequestRef.current === controller) aiRequestRef.current = null;
      setIsGenerating(false);
    }
  };

  const cancelAiGeneration = () => {
    aiRequestRef.current?.abort();
  };

  const save = async () => {
    if (!metadata || isSaving || isResetting || isGenerating) return;
    setError(null);
    setIsSaving(true);
    try {
      const editRequest = {
        ...cropRect,
        sharpness,
        expected_revision: metadata.revision,
      };
      if (aiPreview) {
        await passportsApi.applyVisaAiEdit(submissionId, {
          ...editRequest,
          image: aiPreview.blob,
          previewToken: aiPreview.token,
          prompt: aiPreview.prompt,
        });
      } else {
        await passportsApi.saveImageCrop(submissionId, imageType, editRequest);
      }
      onSaved();
      onClose();
    } catch (saveError) {
      setError(readEditError(saveError, "Could not save these image edits."));
    } finally {
      setIsSaving(false);
    }
  };

  const reset = async () => {
    if (!metadata || isSaving || isResetting || isGenerating) return;
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
      setError(readEditError(resetError, "Could not reset this image."));
    } finally {
      setIsResetting(false);
    }
  };

  const busy = isSaving || isResetting || isGenerating;
  const canReset = Boolean(
    metadata?.crop || metadata?.ai_edited || (metadata?.sharpness ?? 1) > 1,
  );

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/70 p-2 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-edit-title"
    >
      <div ref={dialogRef} className="flex max-h-[96vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-3 sm:px-6 sm:py-4">
          <div>
            <h2 id="passport-edit-title" className="flex items-center gap-2 font-semibold text-slate-950">
              <Pencil className="h-4 w-4 text-blue-600" aria-hidden="true" />
              Edit {label}
            </h2>
            <p className="mt-1 text-xs text-slate-500 sm:text-sm">
              Crop, rotate, and sharpen the saved image without changing its immutable original.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close image editor"
            disabled={busy}
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        {isVisaPhoto && (
          <div className="flex gap-2 border-b border-slate-200 bg-white px-4 py-2 sm:px-6" role="tablist" aria-label="Visa image editing tools">
            <button
              type="button"
              role="tab"
              aria-selected={activePanel === "adjust"}
              onClick={() => setActivePanel("adjust")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${activePanel === "adjust" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}
            >
              <SlidersHorizontal className="h-4 w-4" /> Adjust
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activePanel === "ai"}
              onClick={() => setActivePanel("ai")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${activePanel === "ai" ? "bg-violet-50 text-violet-700" : "text-slate-600 hover:bg-slate-50"}`}
            >
              <Sparkles className="h-4 w-4" /> AI
            </button>
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-slate-100 p-3 sm:p-5">
          {error && (
            <div role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {!sourceObjectUrl || imageSize.width === 0 ? (
            <div className="flex min-h-80 flex-1 items-center justify-center text-sm text-slate-500" role="status">
              {error ? "Image editor unavailable" : <><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading image</>}
            </div>
          ) : activePanel === "ai" && isVisaPhoto ? (
            <VisaAiPanel
              sourceObjectUrl={sourceObjectUrl}
              generatedObjectUrl={aiPreview?.objectUrl ?? null}
              prompt={aiPrompt}
              busy={busy}
              isGenerating={isGenerating}
              onPromptChange={updatePrompt}
              onGenerate={() => void generateAiPreview()}
              onCancelGenerate={cancelAiGeneration}
            />
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-4">
              <div className="flex flex-1 items-center justify-center overflow-auto">
                <div ref={stageRef} className="relative inline-block max-w-full select-none overflow-hidden bg-black shadow-xl">
                  <canvas
                    ref={canvasRef}
                    aria-label={`Editable ${label}`}
                    className="block max-h-[54vh] max-w-full"
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
              <SharpnessControl
                value={sharpness}
                disabled={busy}
                onChange={setSharpness}
              />
            </div>
          )}
        </div>

        <footer className="flex flex-col gap-3 border-t border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:py-4">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" className="gap-2" disabled={busy || !metadata} onClick={() => setCropRect((current) => rotateCropClockwise(current))}>
              <RotateCw className="h-4 w-4" /> Rotate 90 degrees
            </Button>
            <Button type="button" variant="secondary" disabled={busy || !metadata || !canReset} onClick={() => void reset()}>
              {isResetting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Reset edits
            </Button>
          </div>
          <div className="flex gap-2 sm:justify-end">
            <Button type="button" variant="outline" className="flex-1 sm:flex-none" disabled={busy} onClick={onClose}>
              Cancel
            </Button>
            <Button type="button" className="flex-1 gap-2 sm:flex-none" disabled={busy || !metadata} onClick={() => void save()}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save edits
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function VisaAiPanel({
  sourceObjectUrl,
  generatedObjectUrl,
  prompt,
  busy,
  isGenerating,
  onPromptChange,
  onGenerate,
  onCancelGenerate,
}: {
  sourceObjectUrl: string;
  generatedObjectUrl: string | null;
  prompt: string;
  busy: boolean;
  isGenerating: boolean;
  onPromptChange: (value: string) => void;
  onGenerate: () => void;
  onCancelGenerate: () => void;
}) {
  return (
    <div className="grid min-h-[28rem] flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)_minmax(0,1fr)] lg:items-center">
      <ImageComparisonCard title="Current Visa photo" objectUrl={sourceObjectUrl} />
      <div className="rounded-2xl border border-violet-200 bg-white p-4 shadow-sm">
        <label htmlFor="visa-ai-prompt" className="text-sm font-semibold text-slate-900">
          AI edit instruction
        </label>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Request presentation fixes only, such as a clean white background, balanced exposure, or noise reduction. Identity and biometric features cannot be changed.
        </p>
        <textarea
          id="visa-ai-prompt"
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          disabled={busy}
          maxLength={1000}
          rows={8}
          placeholder="Example: Replace the background with an even plain white studio background and balance the lighting. Preserve the person exactly."
          className="mt-3 w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-100 disabled:bg-slate-50"
        />
        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
          <span>{prompt.length}/1000</span>
          <span>Preview is not saved automatically</span>
        </div>
        {isGenerating ? (
          <Button
            type="button"
            variant="outline"
            className="mt-4 w-full gap-2"
            onClick={onCancelGenerate}
          >
            <X className="h-4 w-4" /> Cancel generation
          </Button>
        ) : (
          <Button
            type="button"
            className="mt-4 w-full gap-2 bg-violet-600 hover:bg-violet-700"
            disabled={busy || prompt.trim().length < 3}
            onClick={onGenerate}
          >
            <Sparkles className="h-4 w-4" /> Generate preview
          </Button>
        )}
      </div>
      {generatedObjectUrl ? (
        <ImageComparisonCard title="Generated preview" objectUrl={generatedObjectUrl} />
      ) : (
        <div className="flex min-h-80 items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 text-center text-sm text-slate-500">
          The verified regenerated image will appear here.
        </div>
      )}
    </div>
  );
}

function ImageComparisonCard({ title, objectUrl }: { title: string; objectUrl: string }) {
  return (
    <figure className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <figcaption className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">
        {title}
      </figcaption>
      {/* Blob URLs are authenticated, short-lived, and released when the editor closes. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={objectUrl} alt={title} className="max-h-[58vh] w-full bg-slate-100 object-contain" />
    </figure>
  );
}

function SharpnessControl({
  value,
  disabled,
  onChange,
}: {
  value: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className="mx-auto w-full max-w-2xl rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="passport-image-sharpness" className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <SlidersHorizontal className="h-4 w-4 text-blue-600" /> Sharpness
        </label>
        <output htmlFor="passport-image-sharpness" className="text-sm font-semibold tabular-nums text-blue-700">
          {Math.round(value * 100)}%
        </output>
      </div>
      <input
        id="passport-image-sharpness"
        type="range"
        min="1"
        max="3"
        step="0.05"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(clampSharpness(Number(event.target.value)))}
        className="mt-3 w-full accent-blue-600"
      />
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
        <span>Original</span><span>Maximum</span>
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

function drawEditedImage(
  canvas: HTMLCanvasElement,
  image: HTMLImageElement,
  rotation: PassportImageCropRect["rotation_degrees"],
  sharpness: number,
) {
  const swapsAxes = rotation === 90 || rotation === 270;
  const sourceWidth = image.naturalWidth;
  const sourceHeight = image.naturalHeight;
  const rotatedWidth = swapsAxes ? sourceHeight : sourceWidth;
  const rotatedHeight = swapsAxes ? sourceWidth : sourceHeight;
  const scale = Math.min(1, 1200 / Math.max(rotatedWidth, rotatedHeight));
  canvas.width = Math.max(1, Math.round(rotatedWidth * scale));
  canvas.height = Math.max(1, Math.round(rotatedHeight * scale));
  const context = canvas.getContext("2d", { willReadFrequently: sharpness > 1.001 });
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
  if (sharpness > 1.001) applySharpnessPreview(context, canvas, sharpness);
}

function applySharpnessPreview(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  sharpness: number,
) {
  const width = canvas.width;
  const height = canvas.height;
  if (width < 3 || height < 3) return;
  const source = context.getImageData(0, 0, width, height);
  const target = context.createImageData(width, height);
  target.data.set(source.data);
  const strength = (clampSharpness(sharpness) - 1) * 0.22;
  const centerWeight = 1 + 4 * strength;
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const offset = (y * width + x) * 4;
      const left = offset - 4;
      const right = offset + 4;
      const above = offset - width * 4;
      const below = offset + width * 4;
      for (let channel = 0; channel < 3; channel += 1) {
        target.data[offset + channel] = Math.max(0, Math.min(255,
          source.data[offset + channel] * centerWeight
          - strength * (
            source.data[left + channel]
            + source.data[right + channel]
            + source.data[above + channel]
            + source.data[below + channel]
          ),
        ));
      }
    }
  }
  context.putImageData(target, 0, 0);
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

function clampSharpness(value: number) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(3, Math.max(1, Math.round(value * 20) / 20));
}

function readEditError(error: unknown, fallback: string) {
  if (
    typeof error === "object"
    && error !== null
    && "response" in error
  ) {
    const detail = (error as { response?: { data?: { detail?: unknown } } })
      .response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}
