"use client";

import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type SetStateAction,
} from "react";
import {
  Check,
  Images,
  Loader2,
  Pencil,
  RotateCw,
  Save,
  SlidersHorizontal,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui";
import {
  passportsApi,
  type PassportImageCropRect,
  type PassportImageCropState,
  type PassportImageLibraryItem,
  type PassportImageType,
  type VisaAiGenerationJob,
  type VisaAiLibraryImage,
} from "../api/passports.api";
import {
  fineRotationOffset,
  MAX_FINE_ROTATION,
  MIN_FINE_ROTATION,
  normalizeCrop,
  normalizeRotationDegrees,
  resizeCrop,
  rotatedImageBounds,
  rotateCropClockwise,
  type CropDragMode,
} from "../utils/passport-image-crop-geometry";
import {
  formatPassportImageLibrarySource,
  PASSPORT_LIBRARY_IMAGE_ACCEPT,
  validatePassportLibraryImage,
} from "../utils/passport-image-library";

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

const VISA_AI_JOB_POLL_INTERVAL_MS = 2_000;
const VISA_AI_JOB_POLL_FAILURE_LIMIT = 4;
const DEFAULT_VISA_AI_PROMPT =
  "Regenerate the image of the person in this image to a studio clicked photo for visa application , it should have a plain white background , keep the current details preserved";

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
  const [fineRotation, setFineRotation] = useState(0);
  const [isFineRotating, setIsFineRotating] = useState(false);
  const [sharpness, setSharpness] = useState(1);
  const [sourceObjectUrl, setSourceObjectUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [activePanel, setActivePanel] =
    useState<"adjust" | "library" | "ai">("adjust");
  const [aiPrompt, setAiPrompt] = useState(
    isVisaPhoto ? DEFAULT_VISA_AI_PROMPT : "",
  );
  const [imageLibrary, setImageLibrary] =
    useState<PassportImageLibraryItem[]>([]);
  const [featuredGenerationId, setFeaturedGenerationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isLoadingLibrary, setIsLoadingLibrary] = useState(true);
  const [isUploadingManual, setIsUploadingManual] = useState(false);
  const [usingImageId, setUsingImageId] = useState<string | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const workingImageRef = useRef<HTMLImageElement | null>(null);
  const rotationBaseRef = useRef(0);
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
        const normalizedCrop = normalizeCrop(state.crop ?? FULL_IMAGE_CROP);
        const initialFineRotation = fineRotationOffset(normalizedCrop.rotation_degrees);
        rotationBaseRef.current = normalizeRotationDegrees(
          normalizedCrop.rotation_degrees - initialFineRotation,
        );
        setMetadata(state);
        setCropRect(normalizedCrop);
        setFineRotation(initialFineRotation);
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
    return () => aiRequestRef.current?.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void passportsApi.listImageLibrary(submissionId, imageType, controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setImageLibrary((current) => mergeImageLibraryItems(items, current));
        const latestAiItem = items.find((item) => item.source === "ai_generated");
        setFeaturedGenerationId((current) => current ?? latestAiItem?.id ?? null);
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) {
          setError(readEditError(loadError, "Could not load the image library."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingLibrary(false);
      });
    return () => controller.abort();
  }, [imageType, submissionId]);

  useEffect(() => {
    if (!isVisaPhoto) return;
    const controller = new AbortController();
    aiRequestRef.current?.abort();
    aiRequestRef.current = controller;
    void (async () => {
      try {
        const activeJob = await passportsApi.getActiveVisaAiGenerationJob(
          submissionId,
          controller.signal,
        );
        if (!activeJob || controller.signal.aborted) return;
        setAiPrompt(activeJob.prompt);
        setIsGenerating(true);
        const terminalJob = await waitForVisaAiGenerationJob(
          submissionId,
          activeJob,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          applyTerminalVisaAiJob(
            terminalJob,
            setImageLibrary,
            setFeaturedGenerationId,
            setError,
          );
        }
      } catch (resumeError) {
        if (!controller.signal.aborted) {
          setError(readEditError(
            resumeError,
            "Could not resume the saved Visa photo generation.",
          ));
        }
      } finally {
        if (aiRequestRef.current === controller) {
          aiRequestRef.current = null;
          setIsGenerating(false);
        }
      }
    })();
    return () => controller.abort();
  }, [isVisaPhoto, submissionId]);

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
  }, [workingObjectUrl]);

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
      );
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [
    activePanel,
    cropRect.rotation_degrees,
    imageSize.width,
    isFineRotating,
    sharpness,
    workingObjectUrl,
  ]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current =
      isSaving || isResetting || isUploadingManual || usingImageId !== null;
  }, [isResetting, isSaving, isUploadingManual, usingImageId]);

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

  const updateFineRotation = (value: number) => {
    const nextFineRotation = Math.min(
      MAX_FINE_ROTATION,
      Math.max(MIN_FINE_ROTATION, Math.round(value)),
    );
    setFineRotation(nextFineRotation);
    setCropRect((current) => normalizeCrop({
      ...current,
      rotation_degrees: normalizeRotationDegrees(
        rotationBaseRef.current + nextFineRotation,
      ),
    }));
  };

  const rotateClockwise = () => {
    rotationBaseRef.current = normalizeRotationDegrees(rotationBaseRef.current + 90);
    setCropRect((current) => rotateCropClockwise(current));
  };

  const updatePrompt = (value: string) => {
    setAiPrompt(value);
  };

  const generateAiPreview = async () => {
    const prompt = aiPrompt.trim().split(/\s+/).join(" ");
    if (!metadata || prompt.length < 3 || isGenerating) return;
    setError(null);
    setIsGenerating(true);
    aiRequestRef.current?.abort();
    const controller = new AbortController();
    aiRequestRef.current = controller;
    try {
      const job = await passportsApi.createVisaAiGenerationJob(
        submissionId,
        prompt,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setAiPrompt(job.prompt);
      const terminalJob = await waitForVisaAiGenerationJob(
        submissionId,
        job,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        applyTerminalVisaAiJob(
          terminalJob,
          setImageLibrary,
          setFeaturedGenerationId,
          setError,
        );
      }
    } catch (generationError) {
      if (!controller.signal.aborted) {
        setError(readEditError(
          generationError,
          "Could not generate the Visa photo.",
        ));
      }
    } finally {
      if (aiRequestRef.current === controller) {
        aiRequestRef.current = null;
        setIsGenerating(false);
      }
    }
  };

  const activateLibraryImage = async (itemId: string) => {
    if (!metadata || busyRef.current) return;
    setError(null);
    setUsingImageId(itemId);
    try {
      await passportsApi.useImageLibraryImage(
        submissionId,
        imageType,
        itemId,
        {
        ...FULL_IMAGE_CROP,
        sharpness: 1,
        expected_revision: metadata.revision,
        },
      );
      onSaved();
      onClose();
    } catch (useError) {
      setError(readEditError(useError, "Could not use this saved image."));
    } finally {
      setUsingImageId(null);
    }
  };

  const uploadManualImage = async (file: File) => {
    if (!metadata || busyRef.current) return;
    const validationError = validatePassportLibraryImage(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setIsUploadingManual(true);
    try {
      await passportsApi.uploadImageLibraryImage(
        submissionId,
        imageType,
        file,
        metadata.revision,
      );
      onSaved();
      onClose();
    } catch (uploadError) {
      setError(readEditError(uploadError, "Could not upload this image."));
    } finally {
      setIsUploadingManual(false);
    }
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
      await passportsApi.saveImageCrop(submissionId, imageType, editRequest);
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

  const busy =
    isSaving
    || isResetting
    || isGenerating
    || isUploadingManual
    || usingImageId !== null;
  const closeBlocked =
    isSaving || isResetting || isUploadingManual || usingImageId !== null;
  const canReset = Boolean(
    metadata?.crop || metadata?.ai_edited || (metadata?.sharpness ?? 1) > 1,
  );
  const aiLibrary = imageLibrary.filter(
    (item) => item.source === "ai_generated",
  );

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/70 p-2 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-edit-title"
    >
      <div ref={dialogRef} className="flex max-h-[96vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 px-4 py-3 sm:px-6 sm:py-4">
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
            disabled={closeBlocked}
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div
          className="flex shrink-0 gap-2 overflow-x-auto border-b border-slate-200 bg-white px-4 py-2 sm:px-6"
          role="tablist"
          aria-label={`${label} image editing tools`}
        >
            <button
              type="button"
              role="tab"
              aria-selected={activePanel === "adjust"}
              aria-controls="passport-image-adjust-panel"
              onClick={() => setActivePanel("adjust")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${activePanel === "adjust" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}
            >
              <SlidersHorizontal className="h-4 w-4" /> Adjust
            </button>
          <button
            type="button"
            role="tab"
            aria-selected={activePanel === "library"}
            aria-controls="passport-image-library-panel"
            onClick={() => setActivePanel("library")}
            className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${activePanel === "library" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}
          >
            <Images className="h-4 w-4" /> Library
          </button>
          {isVisaPhoto && (
              <button
                type="button"
                role="tab"
                aria-selected={activePanel === "ai"}
                aria-controls="passport-image-ai-panel"
                onClick={() => setActivePanel("ai")}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${activePanel === "ai" ? "bg-[#C8CE32] text-slate-950" : "text-slate-600 hover:bg-[#C8CE32]/15 hover:text-slate-950"}`}
              >
                <Sparkles className="h-4 w-4" /> AI
              </button>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain bg-slate-100 p-3 sm:p-5">
          {error && (
            <div role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {!metadata || !sourceObjectUrl || imageSize.width === 0 ? (
            <div className="flex min-h-80 flex-1 items-center justify-center text-sm text-slate-500" role="status">
              {error ? "Image editor unavailable" : <><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading image</>}
            </div>
          ) : activePanel === "library" ? (
            <ImageLibraryPanel
              label={label}
              library={imageLibrary}
              busy={busy}
              isLoading={isLoadingLibrary}
              isUploading={isUploadingManual}
              usingImageId={usingImageId}
              onUpload={(file) => void uploadManualImage(file)}
              onUse={(itemId) => void activateLibraryImage(itemId)}
            />
          ) : activePanel === "ai" && isVisaPhoto ? (
            <VisaAiPanel
              currentImageUrl={metadata.cropped_url}
              library={aiLibrary}
              featuredGenerationId={featuredGenerationId}
              prompt={aiPrompt}
              busy={busy}
              isGenerating={isGenerating}
              isLoadingLibrary={isLoadingLibrary}
              usingImageId={usingImageId}
              onPromptChange={updatePrompt}
              onGenerate={() => void generateAiPreview()}
              onUseGeneration={(generationId) => void activateLibraryImage(generationId)}
            />
          ) : (
            <div
              id="passport-image-adjust-panel"
              role="tabpanel"
              className="flex flex-col gap-4"
            >
              <div className="flex w-full items-start justify-center overflow-x-auto pb-1">
                <div ref={stageRef} className="relative inline-block max-w-full select-none overflow-hidden bg-black shadow-xl">
                  <canvas
                    ref={canvasRef}
                    aria-label={`Editable ${label}`}
                    className="block max-w-full"
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
                        className={`absolute h-7 w-7 touch-none rounded-full border-2 border-white bg-black shadow-[0_0_0_2px_rgba(15,23,42,0.9),0_2px_8px_rgba(15,23,42,0.7)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${cornerClassName(corner)}`}
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
              <div className="mx-auto grid w-full max-w-5xl gap-3 sm:grid-cols-2">
                <FineRotationControl
                  value={fineRotation}
                  disabled={busy}
                  onChange={updateFineRotation}
                  onInteractionChange={setIsFineRotating}
                />
                <SharpnessControl
                  value={sharpness}
                  disabled={busy}
                  onChange={setSharpness}
                />
              </div>
            </div>
          )}
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:py-4">
          {activePanel === "library" ? (
            <>
              <p className="text-xs text-slate-500">
                Original, manual, and AI-generated images remain available here.
              </p>
              <Button type="button" variant="outline" disabled={closeBlocked} onClick={onClose}>Close</Button>
            </>
          ) : activePanel === "ai" && isVisaPhoto ? (
            <>
              <p className="text-xs text-slate-500">Generated images are saved automatically in the common Library tab.</p>
              <Button type="button" variant="outline" disabled={closeBlocked} onClick={onClose}>Close</Button>
            </>
          ) : (
            <>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" className="gap-2" disabled={busy || !metadata} onClick={rotateClockwise}>
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
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

function ImageLibraryPanel({
  label,
  library,
  busy,
  isLoading,
  isUploading,
  usingImageId,
  onUpload,
  onUse,
}: {
  label: string;
  library: PassportImageLibraryItem[];
  busy: boolean;
  isLoading: boolean;
  isUploading: boolean;
  usingImageId: string | null;
  onUpload: (file: File) => void;
  onUse: (itemId: string) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <section
      id="passport-image-library-panel"
      role="tabpanel"
      aria-labelledby="passport-image-library-title"
      className="flex min-h-[28rem] flex-1 flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3
            id="passport-image-library-title"
            className="flex items-center gap-2 text-base font-semibold text-slate-900"
          >
            <Images className="h-5 w-5 text-blue-600" aria-hidden="true" />
            Image library
          </h3>
          <p className="mt-1 max-w-2xl text-sm leading-5 text-slate-500">
            Choose any saved {label.toLowerCase()}, or upload a new image. The immutable original stays available whenever one was submitted.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
            {library.length} saved
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept={PASSPORT_LIBRARY_IMAGE_ACCEPT}
            aria-label={`Upload a new ${label} image`}
            className="sr-only"
            disabled={busy}
            onChange={(event) => {
              const selected = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (selected) onUpload(selected);
            }}
          />
          <Button
            type="button"
            variant="outline"
            className="gap-2"
            disabled={busy}
            aria-busy={isUploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            {isUploading ? "Uploading…" : "Upload image"}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div
          className="flex min-h-64 flex-1 items-center justify-center text-sm text-slate-500"
          role="status"
          aria-live="polite"
        >
          <Loader2 className="mr-2 h-5 w-5 animate-spin" aria-hidden="true" />
          Loading saved images
        </div>
      ) : library.length > 0 ? (
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {library.map((item) => {
            const sourceLabel = formatPassportImageLibrarySource(item.source);
            const savedAt = formatLibraryDate(item.created_at);
            const isUsing = usingImageId === item.id;
            return (
              <article
                key={item.id}
                className={`flex min-w-0 flex-col overflow-hidden rounded-xl border bg-white ${
                  item.is_current
                    ? "border-blue-400 ring-2 ring-blue-100"
                    : "border-slate-200"
                }`}
              >
                <div className="relative">
                  {/* Same-origin authorized endpoint; native lazy loading avoids eager library downloads. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    loading="lazy"
                    src={item.image_url}
                    alt={`${sourceLabel} ${label}`}
                    className="h-48 w-full bg-slate-100 object-contain"
                  />
                  <span className={`absolute left-2 top-2 rounded-full px-2.5 py-1 text-[11px] font-semibold shadow-sm ${librarySourceBadgeClass(item.source)}`}>
                    {sourceLabel}
                  </span>
                  {item.is_current && (
                    <span className="absolute right-2 top-2 rounded-full bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm">
                      In use
                    </span>
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-2 p-3">
                  {savedAt && (
                    <p className="text-xs text-slate-500">{savedAt}</p>
                  )}
                  {item.source === "ai_generated" && item.prompt?.trim() && (
                    <p className="line-clamp-2 text-xs leading-5 text-slate-600" title={item.prompt}>
                      {item.prompt}
                    </p>
                  )}
                  <Button
                    type="button"
                    className="mt-auto w-full gap-2"
                    variant={item.is_current ? "secondary" : "primary"}
                    disabled={busy || item.is_current}
                    onClick={() => onUse(item.id)}
                  >
                    {isUsing ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Check className="h-4 w-4" aria-hidden="true" />
                    )}
                    {item.is_current ? "Currently in use" : "Use this image"}
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="mt-5 flex min-h-64 flex-1 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 text-center text-sm text-slate-500">
          No saved images are available for this slot yet. Upload an image to create the first library item.
        </div>
      )}
    </section>
  );
}

function VisaAiPanel({
  currentImageUrl,
  library,
  featuredGenerationId,
  prompt,
  busy,
  isGenerating,
  isLoadingLibrary,
  usingImageId,
  onPromptChange,
  onGenerate,
  onUseGeneration,
}: {
  currentImageUrl: string;
  library: PassportImageLibraryItem[];
  featuredGenerationId: string | null;
  prompt: string;
  busy: boolean;
  isGenerating: boolean;
  isLoadingLibrary: boolean;
  usingImageId: string | null;
  onPromptChange: (value: string) => void;
  onGenerate: () => void;
  onUseGeneration: (generationId: string) => void;
}) {
  const featured = library.find((item) => item.id === featuredGenerationId) ?? library[0] ?? null;
  return (
    <div
      id="passport-image-ai-panel"
      role="tabpanel"
      className="flex min-h-[28rem] flex-1 flex-col gap-5"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)_minmax(0,1fr)] lg:items-center">
      <ImageComparisonCard
        title="Current Visa photo"
        imageUrl={currentImageUrl}
        isCurrent
        isUsing={false}
        disabled
        onUse={() => undefined}
      />
      <div className="rounded-2xl border border-[#C8CE32] bg-white p-4 shadow-sm">
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
          className="mt-3 w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-[#C8CE32] focus:ring-2 focus:ring-[#C8CE32]/30 disabled:bg-slate-50"
        />
        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
          <span>{prompt.length}/1000</span>
          <span>Saved automatically after generation</span>
        </div>
        {isGenerating ? (
          <div className="mt-4" role="status" aria-live="polite">
            <Button
              type="button"
              aria-busy="true"
              className="w-full gap-2 bg-[#C8CE32] text-slate-950 hover:bg-[#C8CE32] disabled:cursor-wait disabled:opacity-100"
              disabled
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Generating and saving…
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            className="mt-4 w-full gap-2 bg-[#C8CE32] text-slate-950 hover:bg-[#C8CE32] hover:brightness-95"
            disabled={busy || prompt.trim().length < 3}
            onClick={onGenerate}
          >
            <Sparkles className="h-4 w-4" /> Generate and save
          </Button>
        )}
      </div>
      {featured ? (
        <ImageComparisonCard
          title="Latest generated image"
          imageUrl={featured.image_url}
          isCurrent={featured.is_current}
          isUsing={usingImageId === featured.id}
          disabled={busy || featured.is_current}
          onUse={() => onUseGeneration(featured.id)}
        />
      ) : isLoadingLibrary ? (
        <div className="flex min-h-80 items-center justify-center rounded-2xl border border-dashed border-[#C8CE32] bg-[#C8CE32]/10 text-sm font-medium text-slate-800" role="status">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-slate-950" aria-hidden="true" /> Loading saved images
        </div>
      ) : (
        <div className="flex min-h-80 items-center justify-center rounded-2xl border border-dashed border-[#C8CE32] bg-white px-6 text-center text-sm text-slate-500">
          Your generated image will appear here and be saved to the library.
        </div>
      )}
      </div>
    </div>
  );
}

function ImageComparisonCard({
  title,
  imageUrl,
  isCurrent,
  isUsing,
  disabled,
  onUse,
}: {
  title: string;
  imageUrl: string;
  isCurrent: boolean;
  isUsing: boolean;
  disabled: boolean;
  onUse: () => void;
}) {
  return (
    <figure className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <figcaption className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">
        {title}
      </figcaption>
      {/* Same-origin endpoints authorize each request and explicitly disable shared caching. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageUrl} alt={title} className="max-h-[58vh] w-full bg-slate-100 object-contain" />
      <div className="border-t border-slate-100 p-3">
        <Button
          type="button"
          className="w-full gap-2 bg-[#C8CE32] text-slate-950 hover:bg-[#C8CE32] hover:brightness-95"
          disabled={disabled}
          onClick={onUse}
        >
          {isUsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          {isCurrent ? "Currently in use" : "Use this image"}
        </Button>
      </div>
    </figure>
  );
}

function FineRotationControl({
  value,
  disabled,
  onChange,
  onInteractionChange,
}: {
  value: number;
  disabled: boolean;
  onChange: (value: number) => void;
  onInteractionChange: (isInteracting: boolean) => void;
}) {
  const formattedValue = `${value > 0 ? "+" : ""}${value}°`;
  return (
    <div className="h-full rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <label
            htmlFor="passport-image-fine-rotation"
            className="flex items-center gap-2 text-sm font-semibold text-slate-800"
          >
            <RotateCw className="h-4 w-4 text-blue-600" /> Fine rotation
          </label>
          <p className="mt-0.5 text-xs text-slate-500">
            Drag to straighten the image one degree at a time.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <output
            htmlFor="passport-image-fine-rotation"
            className="min-w-12 text-right text-sm font-semibold tabular-nums text-blue-700"
            aria-live="polite"
          >
            {formattedValue}
          </output>
          <button
            type="button"
            disabled={disabled || value === 0}
            onClick={() => onChange(0)}
            className="rounded-md px-2 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Reset
          </button>
        </div>
      </div>
      <input
        id="passport-image-fine-rotation"
        type="range"
        min={MIN_FINE_ROTATION}
        max={MAX_FINE_ROTATION}
        step="1"
        value={value}
        disabled={disabled}
        onPointerDown={() => onInteractionChange(true)}
        onPointerUp={() => onInteractionChange(false)}
        onPointerCancel={() => onInteractionChange(false)}
        onLostPointerCapture={() => onInteractionChange(false)}
        onBlur={() => onInteractionChange(false)}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-3 w-full touch-none accent-blue-600"
      />
      <div className="mt-1 flex justify-between text-[11px] tabular-nums text-slate-400">
        <span>{MIN_FINE_ROTATION}°</span>
        <span>0°</span>
        <span>+{MAX_FINE_ROTATION}°</span>
      </div>
    </div>
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
    <div className="h-full w-full rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
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
        <span>Enhanced</span><span>Maximum</span>
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
  isInteractive: boolean,
) {
  const sourceWidth = image.naturalWidth;
  const sourceHeight = image.naturalHeight;
  const rotatedBounds = rotatedImageBounds(sourceWidth, sourceHeight, rotation);
  const maxPreviewDimension = isInteractive ? 800 : 1200;
  const scale = Math.min(
    1,
    maxPreviewDimension / Math.max(rotatedBounds.width, rotatedBounds.height),
  );
  const rotatedWidth = rotatedBounds.width;
  const rotatedHeight = rotatedBounds.height;
  canvas.width = Math.max(1, Math.round(rotatedWidth * scale));
  canvas.height = Math.max(1, Math.round(rotatedHeight * scale));
  const context = canvas.getContext("2d", { willReadFrequently: sharpness > 1.001 });
  if (!context) return;
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = isInteractive ? "medium" : "high";
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
  const effectiveSharpness = 3 + ((clampSharpness(sharpness) - 1) * 2);
  const strength = (effectiveSharpness - 1) * 0.22;
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

function librarySourceBadgeClass(
  source: PassportImageLibraryItem["source"],
): string {
  if (source === "original") return "bg-slate-900 text-white";
  if (source === "manual") return "bg-blue-600 text-white";
  return "bg-[#C8CE32] text-slate-950";
}

function formatLibraryDate(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString();
}

async function waitForVisaAiGenerationJob(
  submissionId: string,
  initialJob: VisaAiGenerationJob,
  signal: AbortSignal,
) {
  let job = initialJob;
  let consecutiveFailures = 0;
  while (job.status === "queued" || job.status === "running") {
    await abortableDelay(VISA_AI_JOB_POLL_INTERVAL_MS, signal);
    try {
      job = await passportsApi.getVisaAiGenerationJob(
        submissionId,
        job.id,
        signal,
      );
      consecutiveFailures = 0;
    } catch (pollError) {
      if (signal.aborted) throw pollError;
      consecutiveFailures += 1;
      if (consecutiveFailures >= VISA_AI_JOB_POLL_FAILURE_LIMIT) {
        throw pollError;
      }
    }
  }
  return job;
}

function abortableDelay(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Polling stopped.", "AbortError"));
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", handleAbort);
      resolve();
    }, milliseconds);
    const handleAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Polling stopped.", "AbortError"));
    };
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

function applyTerminalVisaAiJob(
  job: VisaAiGenerationJob,
  setLibrary: Dispatch<SetStateAction<PassportImageLibraryItem[]>>,
  setFeaturedGenerationId: Dispatch<SetStateAction<string | null>>,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  if (job.status === "succeeded" && job.result) {
    const result = job.result;
    const commonLibraryItem = toCommonAiLibraryItem(result);
    setLibrary((current) => [
      commonLibraryItem,
      ...current.filter((item) => item.id !== result.id),
    ]);
    setFeaturedGenerationId(result.id);
    setError(null);
    return;
  }
  if (job.status === "failed") {
    setError(
      job.error_message?.trim()
      || "Could not generate the Visa photo. Please try again.",
    );
    return;
  }
  setError("The Visa photo was generated, but its saved result is unavailable.");
}

function toCommonAiLibraryItem(
  item: VisaAiLibraryImage,
): PassportImageLibraryItem {
  return {
    ...item,
    image_type: "visa_photo",
    source: "ai_generated",
  };
}

function mergeImageLibraryItems(
  serverItems: PassportImageLibraryItem[],
  currentItems: PassportImageLibraryItem[],
) {
  const serverIds = new Set(serverItems.map((item) => item.id));
  return [
    ...serverItems,
    ...currentItems.filter((item) => !serverIds.has(item.id)),
  ];
}

function readEditError(error: unknown, fallback: string) {
  if (
    typeof error === "object"
    && error !== null
  ) {
    if ("response" in error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}
