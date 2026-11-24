"use client";

import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import {
  passportsApi,
  type PassportImageCropRect,
  type PassportImageCropState,
  type PassportImageType,
} from "../api/passports.api";
import { FULL_IMAGE_CROP, readEditError } from "../utils/passport-image-editor-state";
import { validatePassportLibraryImage } from "../utils/passport-image-library";

type ImageAction = {
  kind: "save" | "reset" | "upload" | "use";
  imageId?: string;
};

interface ImageEditorActionOptions {
  submissionId: string;
  imageType: PassportImageType;
  metadata: PassportImageCropState | null;
  cropRect: PassportImageCropRect;
  sharpness: number;
  isGenerating: boolean;
  busyRef: MutableRefObject<boolean>;
  setError: Dispatch<SetStateAction<string | null>>;
  onSaved: () => void;
  onClose: () => void;
}

export function usePassportImageEditorActions({
  submissionId,
  imageType,
  metadata,
  cropRect,
  sharpness,
  isGenerating,
  busyRef,
  setError,
  onSaved,
  onClose,
}: ImageEditorActionOptions) {
  const [action, setAction] = useState<ImageAction | null>(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  const perform = async (
    next: ImageAction,
    operation: () => Promise<unknown>,
    fallback: string,
  ) => {
    if (busyRef.current || isGenerating) return;
    busyRef.current = true;
    setAction(next);
    setError(null);
    try {
      await operation();
      if (active.current) {
        onSaved();
        onClose();
      }
    } catch (error) {
      if (active.current) setError(readEditError(error, fallback));
    } finally {
      busyRef.current = false;
      if (active.current) setAction(null);
    }
  };

  const save = async () => {
    if (!metadata) return;
    await perform(
      { kind: "save" },
      () => passportsApi.saveImageCrop(submissionId, imageType, {
        ...cropRect, sharpness, expected_revision: metadata.revision,
      }),
      "Could not save these image edits.",
    );
  };

  const reset = async () => {
    if (!metadata) return;
    await perform(
      { kind: "reset" },
      () => passportsApi.resetImageCrop(submissionId, imageType, metadata.revision),
      "Could not reset this image.",
    );
  };

  const activateLibraryImage = async (itemId: string) => {
    if (!metadata) return;
    await perform(
      { kind: "use", imageId: itemId },
      () => passportsApi.useImageLibraryImage(submissionId, imageType, itemId, {
        ...FULL_IMAGE_CROP, sharpness: 1, expected_revision: metadata.revision,
      }),
      "Could not use this saved image.",
    );
  };

  const uploadManualImage = async (file: File) => {
    if (!metadata || busyRef.current || isGenerating) return;
    const validationError = validatePassportLibraryImage(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    await perform(
      { kind: "upload" },
      () => passportsApi.uploadImageLibraryImage(submissionId, imageType, file, metadata.revision),
      "Could not upload this image.",
    );
  };

  return {
    save,
    reset,
    activateLibraryImage,
    uploadManualImage,
    closeBlocked: action !== null,
    isSaving: action?.kind === "save",
    isResetting: action?.kind === "reset",
    isUploadingManual: action?.kind === "upload",
    usingImageId: action?.kind === "use" ? action.imageId ?? null : null,
  };
}
