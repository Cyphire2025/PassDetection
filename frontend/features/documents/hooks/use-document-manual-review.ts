import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ApiError } from "@/lib/api/client";
import type { DistributionDocumentType, DocumentVerificationResult } from "@/types/document-distribution.types";
import { SENSITIVE_STATE_RESET_EVENT } from "@/features/auth/services/session-state";
import { documentDistributionApi } from "../api/document-distribution.api";
import { appendApprovedDocument, applyCompletedManualUploads, emptyDocumentManifest, replaceVerificationFiles, type DocumentManualReviewCandidate } from "../services/document-manual-review";
import { isPassengerMatchedVerificationFile } from "../services/document-upload-batching";
import { clearDocumentUploadRecovery, persistDocumentUploadRecovery, readDocumentUploadRecovery, type DocumentUploadRecoveryPlan } from "../services/document-upload-recovery";

type Progress = { completed: number; total: number; uploaded: number; rejected: number; phase: "approving" | "uploading" };
type VerificationChange = (verification: DocumentVerificationResult) => void;
const errorMessage = (cause: unknown) => (cause as Partial<ApiError> | null)?.message || "Could not finish the selected PDFs. Please try again.";

export function useDocumentManualReview(groupId: string, documentType: DistributionDocumentType) {
  const queryClient = useQueryClient();
  const [candidates, setCandidates] = useState<ReadonlyMap<number, DocumentManualReviewCandidate>>(() => new Map());
  const [selectedIndexes, setSelectedIndexes] = useState<ReadonlySet<number>>(() => new Set());
  const [reviewCandidates, setReviewCandidates] = useState<DocumentManualReviewCandidate[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [pendingUpload, setPendingUpload] = useState<DocumentUploadRecoveryPlan | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  const replaceCandidates = useCallback((next: DocumentManualReviewCandidate[]) => {
    requestRef.current?.abort();
    requestRef.current = null;
    setCandidates(new Map(next.map((candidate) => [candidate.fileIndex, candidate])));
    setSelectedIndexes(new Set());
    setReviewCandidates([]);
    setPending(false);
    setProgress(null);
    setError(null);
    setFeedback(null);
  }, []);

  const restoreUpload = useCallback(() => {
    setPendingUpload(readDocumentUploadRecovery(groupId, documentType, "manual"));
  }, [groupId, documentType]);

  useEffect(() => {
    const clearSensitive = () => { replaceCandidates([]); setPendingUpload(null); };
    window.addEventListener(SENSITIVE_STATE_RESET_EVENT, clearSensitive);
    return () => {
      requestRef.current?.abort();
      requestRef.current = null;
      window.removeEventListener(SENSITIVE_STATE_RESET_EVENT, clearSensitive);
    };
  }, [groupId, documentType, replaceCandidates]);

  const remember = (plan: DocumentUploadRecoveryPlan) => {
    setPendingUpload(plan);
    persistDocumentUploadRecovery(groupId, documentType, plan, "manual");
  };

  const uploadApproved = async (
    initial: DocumentUploadRecoveryPlan,
    initialVerification: DocumentVerificationResult | null,
    onChange: VerificationChange,
    controller: AbortController,
  ) => {
    let plan = { ...initial, manifest: { ...initial.manifest, finalizationStarted: true } };
    let verification = initialVerification;
    remember(plan);
    setProgress({ phase: "uploading", completed: plan.manifest.totalFiles, total: plan.manifest.totalFiles, uploaded: plan.manifest.completedChunks, rejected: 0 });
    await documentDistributionApi.uploadDocuments(groupId, documentType, plan.manifest,
      (value) => {
        if (controller.signal.aborted) return;
        setProgress({ phase: "uploading", completed: value.totalFiles, total: value.totalFiles, uploaded: value.completedFiles, rejected: 0 });
      },
      (manifest) => {
        if (controller.signal.aborted) return;
        plan = { ...plan, manifest: { ...manifest, finalizationStarted: true } };
        remember(plan);
        if (verification) {
          verification = applyCompletedManualUploads(verification, plan);
          onChange(verification);
        }
      }, controller.signal);
    if (controller.signal.aborted) return;
    clearDocumentUploadRecovery(groupId, documentType, "manual");
    setPendingUpload(null);
    setReviewCandidates([]);
    setSelectedIndexes(new Set());
    setFeedback(`${plan.manifest.totalFiles} selected PDF${plan.manifest.totalFiles === 1 ? "" : "s"} approved and uploaded.`);
    void queryClient.invalidateQueries({ queryKey: ["document-distribution"] });
  };

  const approve = async (initialVerification: DocumentVerificationResult, onChange: VerificationChange) => {
    if (!reviewCandidates.length || requestRef.current || pendingUpload) return;
    const chosen = [...reviewCandidates];
    const controller = new AbortController();
    requestRef.current = controller;
    setPending(true);
    setError(null);
    setFeedback(null);
    let verification = initialVerification;
    let plan: DocumentUploadRecoveryPlan = {
      manifest: emptyDocumentManifest(),
      verification: { group_id: groupId, document_type: documentType, files: [], total_count: 0, accepted_count: 0, rejected_count: 0 },
    };
    let rejected = 0;
    try {
      for (const [position, candidate] of chosen.entries()) {
        if (controller.signal.aborted) return;
        setProgress({ phase: "approving", completed: position, total: chosen.length, uploaded: 0, rejected });
        try {
          const result = await documentDistributionApi.manuallyVerifyDocument(groupId, documentType, candidate, controller.signal, plan.manifest.uploadId);
          if (controller.signal.aborted) return;
          if (!result.manual_type_approved) throw new Error("The document type approval was not confirmed.");
          if (isPassengerMatchedVerificationFile(result)) {
            plan = appendApprovedDocument(plan, candidate, result);
            remember(plan);
          } else {
            rejected += 1;
            verification = replaceVerificationFiles(verification, new Map([[candidate.fileIndex, {
              ...result, accepted: false, manual_review_available: false,
              reason: result.match_reason || result.reason || "A confirmed passenger match is still required.",
            }]]));
            onChange(verification);
          }
          setCandidates((current) => { const next = new Map(current); next.delete(candidate.fileIndex); return next; });
          setSelectedIndexes((current) => { const next = new Set(current); next.delete(candidate.fileIndex); return next; });
        } catch (cause) {
          if (controller.signal.aborted) return;
          rejected += 1;
          verification = replaceVerificationFiles(verification, new Map([[candidate.fileIndex, {
            ...verification.files[candidate.fileIndex], reason: errorMessage(cause),
          }]]));
          onChange(verification);
        }
      }
      if (plan.manifest.totalFiles) await uploadApproved(plan, verification, onChange, controller);
      else setReviewCandidates([]);
      if (!controller.signal.aborted && rejected) setError(`${rejected} selected PDF${rejected === 1 ? " still needs" : "s still need"} attention. See the reason beside each rejected file.`);
    } catch (cause) {
      if (!controller.signal.aborted) { setError(errorMessage(cause)); setReviewCandidates([]); }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setPending(false);
        void queryClient.invalidateQueries({ queryKey: ["document-distribution"] });
      }
    }
  };

  const resumeUpload = async (verification: DocumentVerificationResult | null, onChange: VerificationChange) => {
    if (!pendingUpload || requestRef.current) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setPending(true);
    setError(null);
    try { await uploadApproved(pendingUpload, verification, onChange, controller); }
    catch (cause) { if (!controller.signal.aborted) setError(errorMessage(cause)); }
    finally {
      if (requestRef.current === controller) { requestRef.current = null; setPending(false); }
      if (!controller.signal.aborted) void queryClient.invalidateQueries({ queryKey: ["document-distribution"] });
    }
  };

  const forgetUpload = useCallback(() => {
    clearDocumentUploadRecovery(groupId, documentType, "manual");
    setPendingUpload(null);
    setReviewCandidates([]);
  }, [groupId, documentType]);

  const discardUpload = async (verification: DocumentVerificationResult | null, onChange: VerificationChange) => {
    if (!pendingUpload || requestRef.current) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setPending(true);
    setError(null);
    try {
      let retained = false;
      if (pendingUpload.manifest.finalizationStarted) {
        try {
          const result = await documentDistributionApi.abortUpload(groupId, documentType, pendingUpload.manifest.uploadId);
          retained = result.status === "partial_retained";
        }
        catch (cause) { if ((cause as Partial<ApiError>)?.code !== "HTTP_404") throw cause; }
      }
      if (controller.signal.aborted) return;
      if (verification && !retained) {
        const replacements = new Map(pendingUpload.verification.files.flatMap((file) => {
          const index = file.manual_source_index;
          return index !== undefined && verification.files[index]?.filename === file.filename
            ? [[index, { ...file, accepted: false, uploaded: false, manual_uploaded: false, manual_review_available: false, reason: "Upload discarded. Select and check this PDF again to upload it." }] as const]
            : [];
        }));
        onChange(replaceVerificationFiles(verification, replacements));
      }
      forgetUpload();
      setFeedback(retained
        ? "The unfinished upload was closed. Successfully uploaded replacements have been kept; select and check the remaining PDFs again."
        : "Incomplete approved upload discarded. Select and check any remaining PDFs again.");
      void queryClient.invalidateQueries({ queryKey: ["document-distribution"] });
    } catch (cause) { if (!controller.signal.aborted) setError(errorMessage(cause)); }
    finally { if (requestRef.current === controller) { requestRef.current = null; setPending(false); } }
  };

  return {
    candidates, selectedIndexes, reviewCandidates, pending, pendingUpload, error, feedback, progress,
    replaceCandidates, restoreUpload, forgetUpload, discardUpload, resumeUpload, approve,
    toggleSelection: (index: number, selected: boolean) => {
      if (requestRef.current || pendingUpload || !candidates.has(index)) return;
      setSelectedIndexes((current) => { const next = new Set(current); if (selected) next.add(index); else next.delete(index); return next; });
    },
    selectAll: (selected: boolean) => {
      if (!requestRef.current && !pendingUpload) setSelectedIndexes(selected ? new Set(candidates.keys()) : new Set());
    },
    openReview: (index: number) => {
      const candidate = candidates.get(index);
      if (!requestRef.current && !pendingUpload && candidate) setReviewCandidates([candidate]);
    },
    openSelected: () => {
      if (!requestRef.current && !pendingUpload) setReviewCandidates([...candidates.values()].filter((candidate) => selectedIndexes.has(candidate.fileIndex)));
    },
    closeReview: () => { if (!requestRef.current) setReviewCandidates([]); },
  };
}
