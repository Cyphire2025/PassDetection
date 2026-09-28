import { useEffect, useRef } from "react";
import type { PassportGroupSubmissionFilter } from "../api/passports.api";
import { useBulkDocumentFollowUp } from "../hooks/use-passports";
import { mutationErrorMessage } from "./passport-group-model";

type FollowUpOptions = {
  groupId: string;
  selectedPassports: string[];
  canManage: boolean;
  flaggedCount: number | undefined;
  viewStatus: { isLoading: boolean; isFetching: boolean; isPlaceholderData?: boolean; error?: unknown };
  includeDeleted: boolean;
  groupStatus?: string;
  submissionFilter: PassportGroupSubmissionFilter;
  setSubmissionFilter: (filter: PassportGroupSubmissionFilter) => void;
  setPage: (page: number) => void;
  closeMenu: () => void;
  setFeedback: (feedback: { tone: "success" | "error"; message: string } | null) => void;
};

export function usePassportDocumentFollowUp({
  groupId, selectedPassports, canManage: hasPermission, flaggedCount, viewStatus, includeDeleted, groupStatus,
  submissionFilter, setSubmissionFilter, setPage, closeMenu, setFeedback,
}: FollowUpOptions) {
  const mutation = useBulkDocumentFollowUp(groupId);
  const canManage = hasPermission && !includeDeleted && groupStatus !== "archived";
  const isViewReady = !viewStatus.isLoading && !viewStatus.isFetching && !viewStatus.isPlaceholderData && !viewStatus.error;
  const started = useRef(false);

  useEffect(() => {
    if (!isViewReady || flaggedCount !== 0 || submissionFilter !== "document_follow_up") return;
    const timer = window.setTimeout(() => {
      setSubmissionFilter("all");
      setPage(1);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [flaggedCount, isViewReady, setPage, setSubmissionFilter, submissionFilter]);

  function update(flagged: boolean) {
    if (!canManage || !selectedPassports.length || started.current || mutation.isPending) return;
    started.current = true;
    closeMenu();
    setFeedback(null);
    mutation.mutate({ submission_ids: [...selectedPassports], flagged }, {
      onSuccess: (result) => {
        if (result.updated_count === 0) {
          setFeedback({ tone: "success", message: result.flagged
            ? "Selected people are already flagged for document follow-up."
            : "Selected people have no document follow-up flags to clear." });
          return;
        }
        const people = `${result.updated_count} ${result.updated_count === 1 ? "person" : "people"}`;
        setFeedback({
          tone: "success",
          message: result.flagged
            ? `${people} flagged for document follow-up.`
            : `Document follow-up flag cleared for ${people}.`,
        });
      },
      onError: (error) => setFeedback({
        tone: "error",
        message: mutationErrorMessage(error, "Could not update document follow-up flags. Please try again."),
      }),
      onSettled: () => { started.current = false; },
    });
  }

  return { canManage, isPending: mutation.isPending, update };
}
