import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError } from "@/lib/api/client";
import type {
  DistributionDocumentType,
  DocumentVerificationResult,
} from "@/types/document-distribution.types";
import { documentDistributionApi } from "../api/document-distribution.api";
import {
  applyManualDocumentVerification,
  type DocumentManualReviewCandidate,
} from "../services/document-manual-review";
import type { DocumentStagingManifest } from "../services/document-upload-batching";

type ApprovalPlan = ReturnType<typeof applyManualDocumentVerification>;

export function useDocumentManualReview(groupId: string, documentType: DistributionDocumentType) {
  const [candidates, setCandidates] = useState<ReadonlyMap<number, DocumentManualReviewCandidate>>(() => new Map());
  const [reviewIndex, setReviewIndex] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  const replaceCandidates = useCallback((next: DocumentManualReviewCandidate[]) => {
    requestRef.current?.abort();
    requestRef.current = null;
    setCandidates(new Map(next.map((candidate) => [candidate.fileIndex, candidate])));
    setReviewIndex(null);
    setPending(false);
    setError(null);
  }, []);

  useEffect(() => () => {
    requestRef.current?.abort();
    requestRef.current = null;
  }, [groupId, documentType]);

  const reviewCandidate = reviewIndex === null ? null : candidates.get(reviewIndex) ?? null;

  const approve = async (
    verification: DocumentVerificationResult,
    manifest: DocumentStagingManifest,
    onApproved: (plan: ApprovalPlan) => void,
  ) => {
    if (!reviewCandidate || requestRef.current || manifest.finalizationStarted || manifest.completedChunks > 0) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setPending(true);
    setError(null);
    try {
      const result = await documentDistributionApi.manuallyVerifyDocument(
        groupId, documentType, reviewCandidate, controller.signal,
      );
      if (controller.signal.aborted || requestRef.current !== controller) return;
      const plan = applyManualDocumentVerification(reviewCandidate, result, verification, manifest);
      onApproved(plan);
      setCandidates((current) => {
        const next = new Map(current);
        next.delete(reviewCandidate.fileIndex);
        return next;
      });
      setReviewIndex(null);
    } catch (cause) {
      if (!controller.signal.aborted && requestRef.current === controller) {
        setError((cause as Partial<ApiError> | null)?.message || "Could not approve this PDF. Please try again.");
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setPending(false);
      }
    }
  };

  return {
    candidates,
    reviewCandidate,
    pending,
    error,
    replaceCandidates,
    openReview: (index: number) => {
      if (!requestRef.current && candidates.has(index)) {
        setError(null);
        setReviewIndex(index);
      }
    },
    closeReview: () => {
      if (!requestRef.current) setReviewIndex(null);
    },
    approve,
  };
}
