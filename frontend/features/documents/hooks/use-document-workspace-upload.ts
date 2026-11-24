"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DistributionDocumentType, DocumentVerificationResult } from "@/types/document-distribution.types";
import { SENSITIVE_STATE_RESET_EVENT, subscribeToSessionResets } from "@/features/auth/services/session-state";
import { useDocumentReview, useUploadDistributionDocuments, useVerifyDistributionDocuments } from "./use-document-distribution";
import { useDocumentManualReview } from "./use-document-manual-review";
import { useDocumentFilenameConflicts } from "./use-document-filename-conflicts";
import { documentDistributionApi } from "../api/document-distribution.api";
import type { DocumentUploadProgress, DocumentStagingManifest } from "../services/document-upload-batching";
import { clearDocumentUploadRecovery, persistDocumentUploadRecovery, readDocumentUploadRecovery } from "../services/document-upload-recovery";
import { emptyDocumentManifest } from "../services/document-manual-review";
import type { DocumentUploadPhase } from "../components/document-upload-panel";

export function useDocumentWorkspaceUpload(groupId: string, documentType: DistributionDocumentType,
  review: ReturnType<typeof useDocumentReview>, setManualUploadTarget: (target: null) => void) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [verification, setVerification] = useState<DocumentVerificationResult | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressDetail, setProgressDetail] = useState<DocumentUploadProgress | null>(null);
  const [stagingManifest, setStagingManifest] = useState<DocumentStagingManifest | null>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [isAbortUploadDialogOpen, setIsAbortUploadDialogOpen] = useState(false);
  const [phase, setPhase] = useState<DocumentUploadPhase>("idle");
  const [preparingCheck, setPreparingCheck] = useState(false);
  const verify = useVerifyDistributionDocuments(groupId, documentType);
  const { reset: resetVerification } = verify;
  const upload = useUploadDistributionDocuments(groupId, documentType);
  const manualReview = useDocumentManualReview(groupId, documentType);
  const { replaceCandidates: replaceManualReviewCandidates, restoreUpload: restoreManualUpload, forgetUpload: forgetManualUpload } = manualReview;
  const filenameConflicts = useDocumentFilenameConflicts(groupId, documentType);
  const { cancel: cancelFilenameConflicts } = filenameConflicts;
  const reviewableFileIndexes = useMemo(() => new Set(manualReview.candidates.keys()), [manualReview.candidates]);
  const processingUploadIds = useMemo(() => {
    const surfacedIds = review.data?.processing_upload_ids ?? [];
    if (surfacedIds.length > 0) return surfacedIds;
    return review.data?.status === "processing" && review.data.batch_id
      ? [review.data.batch_id]
      : [];
  }, [review.data]);
  const canResumeCurrentUpload = Boolean(
    stagingManifest && processingUploadIds.includes(stagingManifest.uploadId),
  );
  const hasIncompleteUploads = processingUploadIds.length > 0;
  const manualReviewLocked = Boolean(
    hasIncompleteUploads || manualReview.pendingUpload
    || (stagingManifest?.finalizationStarted && stagingManifest.totalFiles > 0),
  );
  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      if (!mounted) return;
      const recovered = readDocumentUploadRecovery(groupId, documentType);
      setVerification(recovered?.verification ?? null);
      setStagingManifest(recovered?.manifest ?? null);
      setSelectedFiles([]);
      setManualUploadTarget(null);
      replaceManualReviewCandidates([]);
      restoreManualUpload();
      resetVerification();
    });

    const abortSensitiveWork = () => {
      activeRequestRef.current?.abort("session-reset");
      activeRequestRef.current = null;
      cancelFilenameConflicts();
      setPreparingCheck(false);
      setSelectedFiles([]);
      replaceManualReviewCandidates([]);
      resetVerification();
      forgetManualUpload();
      setVerification(null);
      setStagingManifest(null);
      setProgressDetail(null);
      setProgress(0);
      setPhase("idle");
      setManualUploadTarget(null);
    };
    window.addEventListener(SENSITIVE_STATE_RESET_EVENT, abortSensitiveWork);
    const unsubscribeSessionResets = subscribeToSessionResets(abortSensitiveWork);
    return () => {
      mounted = false;
      activeRequestRef.current?.abort("document-workspace-unmounted");
      activeRequestRef.current = null;
      window.removeEventListener(SENSITIVE_STATE_RESET_EVENT, abortSensitiveWork);
      unsubscribeSessionResets();
    };
  }, [documentType, groupId, replaceManualReviewCandidates, resetVerification, restoreManualUpload, forgetManualUpload, cancelFilenameConflicts, setManualUploadTarget]);

  const beginAbortableRequest = () => {
    activeRequestRef.current?.abort("document-operation-replaced");
    const controller = new AbortController();
    activeRequestRef.current = controller;
    return controller;
  };

  const releaseRequest = (controller: AbortController) => {
    if (activeRequestRef.current === controller) activeRequestRef.current = null;
  };

  const resetSelection = (files: File[]) => {
    if (manualReview.pending || manualReview.pendingUpload) return;
    activeRequestRef.current?.abort("document-selection-replaced");
    activeRequestRef.current = null;
    cancelFilenameConflicts();
    setPreparingCheck(false);
    clearDocumentUploadRecovery(groupId, documentType);
    setSelectedFiles(files);
    replaceManualReviewCandidates([]);
    resetVerification();
    setVerification(null);
    setStagingManifest(null);
    setSelectionError(null);
    setProgressDetail(null);
    setProgress(0);
    setPhase("idle");
  };

  const checkDocuments = async () => {
    if (activeRequestRef.current || selectedFiles.length === 0 || preparingCheck || manualReview.pending || manualReview.pendingUpload) return;
    const controller = beginAbortableRequest();
    setSelectionError(null);
    setPreparingCheck(true);
    setProgressDetail(null);
    setProgress(0);
    try {
      const currentReview = await documentDistributionApi.getReview(groupId, documentType, controller.signal);
      if (controller.signal.aborted) return;
      const plan = await filenameConflicts.resolve(selectedFiles, currentReview);
      if (controller.signal.aborted || !plan) return;
      setSelectedFiles(plan.files);
      if (!plan.files.length) {
        setSelectionError("All selected copies were skipped. Your original documents have been kept.");
        return;
      }
      clearDocumentUploadRecovery(groupId, documentType);
      setStagingManifest(null);
      replaceManualReviewCandidates([]);
      setPhase("checking");
      const data = await verify.mutateAsync({
        files: plan.files,
        filenameReplacements: plan.filenameReplacements,
        signal: controller.signal,
        onProgress: (value) => {
          if (controller.signal.aborted) return;
          setProgressDetail(value);
          setProgress(value.percent);
        },
      });
      if (controller.signal.aborted) return;
      persistDocumentUploadRecovery(groupId, documentType, { verification: data.verification, manifest: data.stagingManifest });
      setSelectedFiles([]);
      replaceManualReviewCandidates(data.manualReviewCandidates ?? []);
      setVerification(data.verification);
      setStagingManifest(data.stagingManifest);
      setProgress(100);
    } catch (cause) {
      if (!controller.signal.aborted) setSelectionError((cause as Error)?.message || "Could not check the selected PDFs.");
    } finally {
      if (!controller.signal.aborted) {
        setPreparingCheck(false);
        setPhase("idle");
        resetVerification();
      }
      releaseRequest(controller);
    }
  };

  const acceptedFileCount = stagingManifest?.totalFiles ?? 0;
  const startUpload = () => {
    if (activeRequestRef.current || acceptedFileCount === 0 || preparingCheck || manualReview.pending || manualReview.pendingUpload) return;
    if (hasIncompleteUploads && !canResumeCurrentUpload) {
      setSelectionError(
        "Discard the incomplete upload before starting another PDF upload.",
      );
      return;
    }
    const activeManifest = stagingManifest ? { ...stagingManifest, finalizationStarted: true } : null;
    const activeVerification = verification;
    if (!activeManifest || !activeVerification) {
      setSelectionError("Check the selected PDFs again before uploading them.");
      return;
    }
    const controller = beginAbortableRequest();
    setSelectionError(null);
    setPhase("uploading");
    setStagingManifest(activeManifest);
    persistDocumentUploadRecovery(groupId, documentType, {
      verification: activeVerification,
      manifest: activeManifest,
    });
    setProgressDetail(null);
    setProgress(0);
    upload.mutate(
      {
        manifest: activeManifest,
        signal: controller.signal,
        onManifestChange: (manifest) => {
          if (controller.signal.aborted) return;
          setStagingManifest(manifest);
          persistDocumentUploadRecovery(groupId, documentType, {
            verification: activeVerification,
            manifest,
          });
        },
        onProgress: (value) => {
          if (controller.signal.aborted) return;
          setPhase("uploading");
          setProgressDetail(value);
          setProgress(value.percent);
        },
      },
      {
        onSuccess: () => {
          if (controller.signal.aborted) return;
          const uploadedVerification = {
            ...activeVerification,
            files: activeVerification.files.map((file) => file.accepted ? { ...file, uploaded: true } : file),
          };
          const remainingManifest = emptyDocumentManifest();
          persistDocumentUploadRecovery(groupId, documentType, { verification: uploadedVerification, manifest: remainingManifest });
          setSelectedFiles([]);
          setVerification(uploadedVerification);
          setStagingManifest(remainingManifest);
          setProgressDetail(null);
          setProgress(100);
          setPhase("idle");
        },
        onError: () => {
          if (controller.signal.aborted) return;
          setPhase("idle");
        },
        onSettled: () => releaseRequest(controller),
      },
    );
  };

  const updateManualVerification = (next: DocumentVerificationResult) => {
    setVerification(next);
    if (stagingManifest) persistDocumentUploadRecovery(groupId, documentType, { verification: next, manifest: stagingManifest });
  };
  return {
    selectedFiles, setSelectedFiles, verification, setVerification, progress, setProgress, progressDetail, setProgressDetail,
    stagingManifest, setStagingManifest, selectionError, setSelectionError, isAbortUploadDialogOpen, setIsAbortUploadDialogOpen,
    phase, setPhase, preparingCheck, verify, upload, manualReview, filenameConflicts, reviewableFileIndexes,
    processingUploadIds, canResumeCurrentUpload, hasIncompleteUploads, manualReviewLocked,
    replaceManualReviewCandidates, forgetManualUpload, resetSelection, checkDocuments, startUpload, updateManualVerification,
    acceptedFileCount: stagingManifest?.totalFiles ?? 0,
  };
}
