"use client";

import { useCallback, useRef, useState } from "react";
import { useModalKeyboardBoundary } from "@/components/ui/modal-keyboard-boundary";
import type { PassportImageType } from "../api/passports.api";
import { usePassportImageEditorActions } from "./use-passport-image-editor-actions";
import { usePassportImageEditorDraft } from "./use-passport-image-editor-draft";
import { usePassportImageEditorSource } from "./use-passport-image-editor-source";
import { useVisaAiImageGeneration } from "./use-visa-ai-image-generation";

export interface PassportImageCropEditorProps {
  submissionId: string;
  imageType: PassportImageType;
  label: string;
  returnFocusTarget: HTMLButtonElement;
  onClose: () => void;
  onSaved: () => void;
}

export function usePassportImageCropEditor(props: PassportImageCropEditorProps) {
  const { submissionId, imageType, onSaved, onClose, returnFocusTarget } = props;
  const isVisaPhoto = imageType === "visa_photo";
  const [error, setError] = useState<string | null>(null);
  const [activePanel, setActivePanel] = useState<"adjust" | "library" | "ai">("adjust");
  const busyRef = useRef(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const source = usePassportImageEditorSource(submissionId, imageType, setError);
  const draft = usePassportImageEditorDraft(
    source.metadata, source.sourceObjectUrl, activePanel, busyRef, setError,
  );
  const ai = useVisaAiImageGeneration({
    submissionId,
    isVisaPhoto,
    canGenerate: Boolean(source.metadata),
    imageLibrary: source.imageLibrary,
    setImageLibrary: source.setImageLibrary,
    setError,
  });
  const actions = usePassportImageEditorActions({
    submissionId,
    imageType,
    metadata: source.metadata,
    cropRect: draft.cropRect,
    sharpness: draft.sharpness,
    isGenerating: ai.isGenerating,
    busyRef,
    setError,
    onSaved,
    onClose,
  });
  const resolveReturnFocus = useCallback(() => returnFocusTarget, [returnFocusTarget]);
  const close = () => { if (!busyRef.current) onClose(); };
  const handleKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: true,
    canClose: !actions.closeBlocked,
    onClose: close,
    returnFocusTarget: resolveReturnFocus,
  });
  const busy = actions.closeBlocked || ai.isGenerating;
  const canReset = Boolean(source.metadata?.crop || source.metadata?.ai_edited || (source.metadata?.sharpness ?? 1) > 1);
  const aiLibrary = source.imageLibrary.filter((item) => item.source === "ai_generated");
  return {
    ...source,
    ...draft,
    ...ai,
    ...actions,
    isVisaPhoto,
    error,
    activePanel,
    setActivePanel,
    dialogRef,
    handleKeyDown,
    close,
    busy,
    canReset,
    aiLibrary,
  };
}
