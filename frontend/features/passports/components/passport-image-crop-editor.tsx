"use client";

import { Images, Loader2, Pencil, Save, ShieldCheck, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui";
import { usePassportImageCropEditor, type PassportImageCropEditorProps } from "../hooks/use-passport-image-crop-editor";
import { FULL_IMAGE_CROP } from "../utils/passport-image-editor-state";
import { PassportImageAdjustWorkspace } from "./passport-image-adjust-workspace";
import { ImageLibraryPanel } from "./passport-image-library-panel";
import { VisaAiPanel } from "./visa-ai-image-panel";

export function PassportImageCropEditor(props: PassportImageCropEditorProps) {
  return <PassportImageCropEditorSession key={`${props.submissionId}:${props.imageType}`} {...props} />;
}

function PassportImageCropEditorSession(props: PassportImageCropEditorProps) {
  const { label } = props;
  const { metadata, cropRect, fineRotation, sharpness, sourceObjectUrl, imageSize, activePanel, setActivePanel,
    aiPrompt, setAiPrompt, imageLibrary, featuredGenerationId, error, isSaving, isResetting, isGenerating,
    isLoadingLibrary, isUploadingManual, usingImageId, stageRef, canvasRef, dialogRef, handleKeyDown,
    isVisaPhoto, closeBlocked, busy, canReset, hasChanges, aiLibrary, beginPointerDrag, movePointerDrag,
    endPointerDrag, handleKeyboard, rotate, updateFineRotation, setIsFineRotating, setSharpness, setCropRect,
    undoChanges, setPreviewDimension, uploadManualImage, activateLibraryImage, generateAiPreview, save, reset, close,
  } = usePassportImageCropEditor(props);

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/60 sm:p-4"
      ref={dialogRef}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="passport-edit-title"
    >
      <div className="flex h-[100dvh] max-h-[900px] w-full max-w-[1360px] flex-col overflow-hidden bg-white shadow-2xl sm:h-[calc(100dvh-2rem)] sm:rounded-2xl">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 px-4 py-3 sm:px-6 sm:py-4">
          <div>
            <h2 id="passport-edit-title" className="flex items-center gap-2 font-semibold text-slate-950">
              <Pencil className="h-4 w-4 text-blue-600" aria-hidden="true" />
              Edit {label}
            </h2>
            <p className="mt-1 text-xs text-slate-500 sm:text-sm">
              Fine-tune the document before saving. Your original stays safely in the library.
            </p>
          </div>
          <button
            data-dialog-initial-focus
            type="button"
            aria-label="Close image editor"
            disabled={closeBlocked}
            onClick={close}
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
              id="passport-image-adjust-tab"
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

        <div className={`flex min-h-0 flex-1 flex-col overscroll-contain bg-slate-50 ${activePanel === "adjust" ? "overflow-hidden" : "overflow-y-auto p-4 sm:p-5"}`}>
          {error && (
            <div role="alert" className="m-3 shrink-0 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {!metadata || !sourceObjectUrl || imageSize.width === 0 ? (
            <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-slate-500" role="status">
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
              onPromptChange={setAiPrompt}
              onGenerate={() => void generateAiPreview()}
              onUseGeneration={(generationId) => void activateLibraryImage(generationId)}
            />
          ) : (
            <PassportImageAdjustWorkspace
              label={label}
              imageSize={imageSize}
              crop={cropRect}
              fineRotation={fineRotation}
              sharpness={sharpness}
              busy={busy}
              hasChanges={hasChanges}
              canvasRef={canvasRef}
              stageRef={stageRef}
              onBeginDrag={beginPointerDrag}
              onMoveDrag={movePointerDrag}
              onEndDrag={endPointerDrag}
              onCropKeyDown={handleKeyboard}
              onRotate={rotate}
              onFineRotation={updateFineRotation}
              onRotationInteraction={setIsFineRotating}
              onSharpness={setSharpness}
              onFullImage={() => setCropRect(current => ({ ...FULL_IMAGE_CROP, rotation_degrees: current.rotation_degrees }))}
              onUndo={undoChanges}
              onPreviewSizeChange={setPreviewDimension}
            />
          )}
        </div>

        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-white px-3 py-3 sm:px-6 sm:py-4">
          {activePanel === "library" ? (
            <>
              <p className="text-xs text-slate-500">
                Original, manual, and AI-generated images remain available here.
              </p>
              <Button type="button" variant="outline" disabled={closeBlocked} onClick={close}>Close</Button>
            </>
          ) : activePanel === "ai" && isVisaPhoto ? (
            <>
              <p className="text-xs text-slate-500">Generated images are saved automatically in the common Library tab.</p>
              <Button type="button" variant="outline" disabled={closeBlocked} onClick={close}>Close</Button>
            </>
          ) : (
            <>
          <div className="flex shrink-0 items-center gap-3">
            <span className="hidden items-center gap-1.5 text-xs text-slate-500 sm:inline-flex">
              <ShieldCheck className="h-4 w-4 text-blue-600" aria-hidden="true" /> Original preserved
            </span>
            <Button type="button" variant="ghost" size="sm" disabled={busy || !metadata || !canReset} onClick={() => void reset()}>
              {isResetting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Reset edits
            </Button>
            {hasChanges ? <span className="hidden text-xs font-medium text-amber-700 xl:inline">Unsaved changes</span> : null}
          </div>
          <div className="ml-auto flex shrink-0 gap-2 sm:justify-end">
            <Button type="button" variant="outline" className="flex-1 sm:flex-none" disabled={busy} onClick={close}>
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
