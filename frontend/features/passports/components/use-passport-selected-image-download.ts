"use client";

import { isDownloadCancelled } from "@/lib/api/download-destination";
import { useRef } from "react";
import { useExportSelectedPassportImages } from "../hooks/use-passports";
import { MAX_SELECTED_IMAGE_DOWNLOAD } from "./passport-group-bindings";
import { mutationErrorMessage } from "./passport-group-model";
import type { Dispatch, SetStateAction } from "react";

export function usePassportSelectedImageDownload(groupId: string, groupName: string | undefined, selectedPassports: string[], setImportMessage: Dispatch<SetStateAction<string | null>>) {
  const exportSelectedImages = useExportSelectedPassportImages();
  const selectedImageDownloadStartedRef = useRef(false);
  const handleSelectedPassportDownload = () => {
    if (selectedPassports.length === 0 ||
      selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD ||
      selectedImageDownloadStartedRef.current ||
      exportSelectedImages.isPending) {
      return;
    }
    selectedImageDownloadStartedRef.current = true;
    setImportMessage(null);
    exportSelectedImages.mutate({
      groupId,
      groupName: groupName,
      submissionIds: [...selectedPassports],
    }, {
      onError: (downloadError) => {
        if (isDownloadCancelled(downloadError))
          return;
        setImportMessage(mutationErrorMessage(downloadError, "Selected passport download failed"));
      },
      onSettled: () => {
        selectedImageDownloadStartedRef.current = false;
      },
    });
  };
  return { exportSelectedImages, handleSelectedPassportDownload };
}
