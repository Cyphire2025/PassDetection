"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DocumentBatchReview } from "@/types/document-distribution.types";
import {
  createDocumentFilenameConflictSession,
  finishDocumentFilenameConflicts,
  nextDocumentFilenameConflict,
  resolveDocumentFilenameConflict,
  type DocumentFilenameConflict,
  type DocumentFilenameConflictChoice,
  type DocumentFilenameConflictSession,
  type DocumentFilenameResolutionPlan,
} from "../services/document-filename-conflicts";

interface PendingResolution {
  session: DocumentFilenameConflictSession;
  complete: (plan: DocumentFilenameResolutionPlan | null) => void;
}

/** A page-local decision step; cancellation and scope changes never mutate saved PDFs. */
export function useDocumentFilenameConflicts(groupId: string, documentType: string) {
  const pendingRef = useRef<PendingResolution | null>(null);
  const [conflict, setConflict] = useState<DocumentFilenameConflict | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cancel = useCallback(() => {
    const pending = pendingRef.current;
    pendingRef.current = null;
    pending?.complete(null);
    setConflict(null);
    setError(null);
  }, []);

  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      if (!mounted) return;
      setConflict(null);
      setError(null);
    });
    return () => {
      mounted = false;
      const pending = pendingRef.current;
      pendingRef.current = null;
      pending?.complete(null);
    };
  }, [groupId, documentType]);

  const resolve = useCallback((files: readonly File[], review: DocumentBatchReview) => {
    cancel();
    const session = createDocumentFilenameConflictSession(files, review, groupId, documentType);
    const next = nextDocumentFilenameConflict(session);
    if (!next) return Promise.resolve(finishDocumentFilenameConflicts(session));
    return new Promise<DocumentFilenameResolutionPlan | null>((complete) => {
      pendingRef.current = { session, complete };
      setConflict(next);
    });
  }, [cancel, documentType, groupId]);

  const choose = useCallback((choice: DocumentFilenameConflictChoice, applyToRemaining = false) => {
    const pending = pendingRef.current;
    if (!pending) return;
    setError(null);
    try {
      const next = resolveDocumentFilenameConflict(pending.session, choice, applyToRemaining);
      if (next) {
        setConflict(next);
        return;
      }
      const result = finishDocumentFilenameConflicts(pending.session);
      pendingRef.current = null;
      setConflict(null);
      pending.complete(result);
    } catch (cause) {
      setConflict(nextDocumentFilenameConflict(pending.session));
      setError(cause instanceof Error ? cause.message : "The filename decision could not be completed.");
    }
  }, []);

  return { conflict, error, isResolving: conflict !== null, resolve, choose, cancel };
}
