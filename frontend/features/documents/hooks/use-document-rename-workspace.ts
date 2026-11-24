"use client";
import { useRef, useState } from "react";
import type { RenameDocumentBatch } from "@/types/document-rename.types";
import {
  useAnalyzeRenameDocuments, useDeleteRenameBatches, useOpenRenameBatch, useRenameBatches,
} from "./use-document-rename";
import {
  createDocumentUploadSession, type DocumentUploadProgress, type DocumentUploadSession,
} from "../services/document-upload-batching";

export function useDocumentRenameWorkspace() {
  const [title, setTitle] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [result, setResult] = useState<RenameDocumentBatch | null>(null);
  const [selectedBatchIds, setSelectedBatchIds] = useState<string[]>([]);
  const [progress, setProgress] = useState(0);
  const [progressDetail, setProgressDetail] = useState<DocumentUploadProgress | null>(null);
  const [uploadSession, setUploadSession] = useState<DocumentUploadSession | null>(null);
  const [uploadSessionTitle, setUploadSessionTitle] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "analyzing">("idle");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const analyze = useAnalyzeRenameDocuments();
  const batches = useRenameBatches();
  const openBatch = useOpenRenameBatch();
  const deleteBatches = useDeleteRenameBatches();
  const startAnalyze = () => {
    if (selectedFiles.length === 0 || !title.trim()) return;
    let activeSession = uploadSession;
    let activeTitle = uploadSessionTitle;
    if (!activeSession) {
      try {
        activeSession = createDocumentUploadSession(selectedFiles);
        activeTitle = title.trim();
        setUploadSession(activeSession);
        setUploadSessionTitle(activeTitle);
      } catch (error) {
        setSelectionError(error instanceof Error ? error.message : "The selected PDFs are invalid");
        return;
      }
    }
    setSelectionError(null);
    setResult(null);
    setPhase("analyzing");
    setProgressDetail(null);
    setProgress(0);
    analyze.mutate(
      {
        title: activeTitle ?? title.trim(),
        files: selectedFiles,
        session: activeSession,
        onProgress: (value) => {
          setProgressDetail(value);
          setProgress(value.percent);
        },
      },
      {
        onSuccess: (data) => {
          setResult(data);
          setTitle("");
          setSelectedFiles([]);
          setUploadSession(null);
          setUploadSessionTitle(null);
          setProgressDetail(null);
          setProgress(100);
          setPhase("idle");
        },
        onError: () => setPhase("idle"),
      },
    );
  };
  return {
    title, setTitle, selectedFiles, setSelectedFiles, result, setResult,
    selectedBatchIds, setSelectedBatchIds, progress, setProgress,
    progressDetail, setProgressDetail, uploadSession, setUploadSession,
    setUploadSessionTitle, selectionError, setSelectionError, phase,
    inputRef, analyze, batches, openBatch, deleteBatches, startAnalyze,
  };
}
export type DocumentRenameWorkspace = ReturnType<typeof useDocumentRenameWorkspace>;
