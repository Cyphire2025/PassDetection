"use client";

import { useRef, useState } from "react";
import type { PassportDocumentImportPreview } from "../api/passports.api";
import {
  useImportPassportGroup,
  usePreviewPassportDocuments,
  useSavePassportDocuments,
} from "../hooks/use-passports";

export function usePassportGroupImports(groupId: string) {
  const importMutation = useImportPassportGroup(groupId);
  const passportPreviewMutation = usePreviewPassportDocuments(groupId);
  const passportSaveMutation = useSavePassportDocuments(groupId);
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const passportImportInputRef = useRef<HTMLInputElement | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [passportImportFiles, setPassportImportFiles] = useState<File[]>([]);
  const [passportImportPreview, setPassportImportPreview] = useState<PassportDocumentImportPreview | null>(null);
  const [passportImportProgress, setPassportImportProgress] = useState<{
    processed: number;
    total: number;
    label: string;
  } | null>(null);
  const handlePassportImportFiles = (files: File[]) => {
    setImportMessage(null);
    setPassportImportPreview(null);
    setPassportImportFiles(files);
    setPassportImportProgress({
      processed: 0,
      total: files.reduce((sum, file) => sum + file.size, 0),
      label: "Uploading files for document check",
    });
    passportPreviewMutation.mutate({
      files,
      onProgress: (progress) => {
        setPassportImportProgress({
          processed: progress.loaded,
          total: progress.total,
          label: progress.phase === "uploading"
            ? "Uploading files for document check"
            : "Checking documents against the full group",
        });
      },
    }, {
      onSuccess: (preview) => {
        setPassportImportPreview(preview);
        setPassportImportProgress(null);
      },
      onError: (previewError) => {
        setPassportImportFiles([]);
        setPassportImportProgress(null);
        setImportMessage(previewError instanceof Error
          ? previewError.message
          : "Passport document check failed");
      },
    });
  };
  return {
    importMutation,
    passportPreviewMutation,
    passportSaveMutation,
    importInputRef,
    passportImportInputRef,
    importMessage,
    setImportMessage,
    passportImportFiles,
    setPassportImportFiles,
    passportImportPreview,
    setPassportImportPreview,
    passportImportProgress,
    setPassportImportProgress,
    handlePassportImportFiles,
  };
}
