"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import {
  passportsApi,
  type PassportImageCropState,
  type PassportImageLibraryItem,
  type PassportImageType,
} from "../api/passports.api";
import { mergeImageLibraryItems, readEditError } from "../utils/passport-image-editor-state";

export function usePassportImageEditorSource(
  submissionId: string,
  imageType: PassportImageType,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  const [metadata, setMetadata] = useState<PassportImageCropState | null>(null);
  const [sourceObjectUrl, setSourceObjectUrl] = useState<string | null>(null);
  const [imageLibrary, setImageLibrary] = useState<PassportImageLibraryItem[]>([]);
  const [isLoadingLibrary, setIsLoadingLibrary] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    void passportsApi.getImageCrop(submissionId, imageType)
      .then(async (state) => {
        if (controller.signal.aborted) return;
        const blob = await passportsApi.getEditableImage(state.editable_source_url, controller.signal);
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setMetadata(state);
        setSourceObjectUrl(objectUrl);
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) setError(readEditError(loadError, "Could not load this image for editing."));
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageType, submissionId, setError]);

  useEffect(() => {
    const controller = new AbortController();
    void passportsApi.listImageLibrary(submissionId, imageType, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setImageLibrary((current) => mergeImageLibraryItems(items, current));
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) setError(readEditError(loadError, "Could not load the image library."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingLibrary(false);
      });
    return () => controller.abort();
  }, [imageType, submissionId, setError]);

  return { metadata, sourceObjectUrl, imageLibrary, setImageLibrary, isLoadingLibrary };
}
