"use client";

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  FileQuestion,
  Plane,
  Save,
  Search,
  Send,
  Trash2,
} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceHeaderContext,
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatConfidence } from "@/lib/utils/format";
import type {
  DistributedDocument,
  DocumentPassengerReviewRow,
  DocumentVerificationResult,
} from "@/types/document-distribution.types";
import {
  useAbortDistributionUploads,
  useDeleteDistributionDocuments,
  useDocumentDeliveryPreview,
  useDocumentGroups,
  useDocumentReview,
  useReuploadPassengerDocument,
  useSaveDocumentBatch,
  useSendDocumentWhatsAppBroadcast,
  useUnassignDistributionDocuments,
  useUploadDistributionDocuments,
  useVerifyDistributionDocuments,
} from "../hooks/use-document-distribution";
import {
  type DocumentUploadProgress,
  type DocumentUploadSession,
} from "../services/document-upload-batching";
import {
  type DocumentDistributionLane,
} from "../config/document-distribution-lanes";
import {
  AbortIncompleteUploadDialog,
  DocumentDeliveryPreviewDialog,
  RemoveAssignmentsDialog,
} from "./document-workspace-dialogs";
import {
  DocumentRowActionMenu,
  DocumentSentStatus,
  MatchBadge,
  VerificationPanel,
} from "./document-workspace-review";
import {
  DocumentUploadPanel,
  type DocumentUploadPhase,
} from "./document-upload-panel";
import { FlightTicketLaneNavigation } from "./flight-ticket-lane-navigation";

function reviewRowDocuments(row: DocumentPassengerReviewRow): DistributedDocument[] {
  if (row.documents?.length) return row.documents;
  return row.document ? [row.document] : [];
}

type ReviewFilter = "all" | "assigned" | "missing" | "sent" | "not_sent";

const SENT_DOCUMENT_STATUSES = new Set(["submitted", "sent", "delivered", "read"]);

export function DocumentWorkspace({
  groupId,
  lane,
}: {
  groupId: string;
  lane: DocumentDistributionLane;
}) {
  const documentType = lane.documentType;
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [verification, setVerification] = useState<DocumentVerificationResult | null>(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [reviewSearchQuery, setReviewSearchQuery] = useState("");
  const [pendingRemovalDocumentIds, setPendingRemovalDocumentIds] = useState<string[] | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressDetail, setProgressDetail] = useState<DocumentUploadProgress | null>(null);
  const [uploadSession, setUploadSession] = useState<DocumentUploadSession | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [isAbortUploadDialogOpen, setIsAbortUploadDialogOpen] = useState(false);
  const [phase, setPhase] = useState<DocumentUploadPhase>("idle");
  const [isSendPreviewOpen, setIsSendPreviewOpen] = useState(false);
  const [deliveryDocumentIds, setDeliveryDocumentIds] = useState<string[] | null>(null);
  const [deliveryResendDocumentIds, setDeliveryResendDocumentIds] = useState<string[]>([]);
  const [deliveryMessageContent1, setDeliveryMessageContent1] = useState<string | null>(null);
  const [deliveryMessageContent2, setDeliveryMessageContent2] = useState<string | null>(null);
  const [deliveryFeedback, setDeliveryFeedback] = useState<string | null>(null);
  const { data: groups = [] } = useDocumentGroups();
  const group = groups.find((item) => item.group_id === groupId);
  const review = useDocumentReview(groupId, documentType);
  const verify = useVerifyDistributionDocuments(groupId, documentType);
  const upload = useUploadDistributionDocuments(groupId, documentType);
  const abortUploads = useAbortDistributionUploads(groupId, documentType);
  const reupload = useReuploadPassengerDocument(groupId, documentType);
  const deleteDocuments = useDeleteDistributionDocuments(groupId, documentType);
  const unassignDocuments = useUnassignDistributionDocuments(groupId, documentType);
  const save = useSaveDocumentBatch(groupId, documentType);
  const deliveryPreview = useDocumentDeliveryPreview(
    groupId,
    documentType,
    isSendPreviewOpen,
  );
  const sendDocuments = useSendDocumentWhatsAppBroadcast(groupId, documentType);
  const LaneIcon = lane.category === "visa" ? FileCheck2 : Plane;
  const documentTypeOperationPending =
    phase !== "idle" ||
    verify.isPending ||
    upload.isPending ||
    abortUploads.isPending ||
    reupload.isPending ||
    deleteDocuments.isPending ||
    unassignDocuments.isPending ||
    save.isPending ||
    sendDocuments.isPending;
  const hasUncommittedSelection =
    selectedFiles.length > 0 || verification !== null || uploadSession !== null;
  const processingUploadIds = useMemo(() => {
    const surfacedIds = review.data?.processing_upload_ids ?? [];
    if (surfacedIds.length > 0) return surfacedIds;
    return review.data?.status === "processing" && review.data.batch_id
      ? [review.data.batch_id]
      : [];
  }, [review.data]);
  const canResumeCurrentUpload = Boolean(
    uploadSession && processingUploadIds.includes(uploadSession.uploadId),
  );
  const hasIncompleteUploads = processingUploadIds.length > 0;
  const reviewRows = useMemo(
    () => review.data?.review_rows ?? [],
    [review.data?.review_rows],
  );
  const reviewCounts = useMemo(() => {
    const assigned = reviewRows.filter((row) => reviewRowDocuments(row).length > 0);
    const sent = assigned.filter((row) =>
      reviewRowDocuments(row).some((document) =>
        SENT_DOCUMENT_STATUSES.has(document.delivery_status),
      ),
    );
    const notSent = assigned.filter((row) =>
      reviewRowDocuments(row).some(
        (document) => !SENT_DOCUMENT_STATUSES.has(document.delivery_status),
      ),
    );
    return {
      all: reviewRows.length,
      assigned: assigned.length,
      missing: reviewRows.length - assigned.length,
      sent: sent.length,
      not_sent: notSent.length,
    };
  }, [reviewRows]);
  const assignmentIssues = useMemo(() => {
    if (review.data?.assignment_issues) return review.data.assignment_issues;
    return (review.data?.unmatched_documents ?? []).map((document) => ({
      document_id: document.id,
      original_filename: document.original_filename,
      code: "no_unique_passenger_match",
      reason: document.match_reason || "No unique passenger match was found.",
      url: document.url,
    }));
  }, [review.data]);
  const physicalFileCount = review.data?.physical_file_count ?? review.data?.uploaded_count ?? 0;
  const assignedFileCount =
    review.data?.assigned_file_count ?? Math.max(physicalFileCount - assignmentIssues.length, 0);
  const assignedPassengerCount =
    review.data?.assigned_passenger_count ?? reviewCounts.assigned;
  const needsAssignmentCount =
    review.data?.needs_assignment_count ?? assignmentIssues.length;
  const visibleReviewRows = useMemo(
    () => {
      const normalizedSearch = reviewSearchQuery.trim().toLocaleLowerCase();
      return reviewRows.filter((row) => {
        if (
          normalizedSearch &&
          !row.passenger_name.toLocaleLowerCase().includes(normalizedSearch)
        ) {
          return false;
        }
        const documents = reviewRowDocuments(row);
        if (reviewFilter === "assigned") return documents.length > 0;
        if (reviewFilter === "missing") return documents.length === 0;
        if (reviewFilter === "sent") {
          return documents.some((document) =>
            SENT_DOCUMENT_STATUSES.has(document.delivery_status),
          );
        }
        if (reviewFilter === "not_sent") {
          return documents.some(
            (document) => !SENT_DOCUMENT_STATUSES.has(document.delivery_status),
          );
        }
        return true;
      });
    },
    [reviewFilter, reviewRows, reviewSearchQuery],
  );
  const acceptedFiles = useMemo(() => {
    if (!uploadSession) return [];
    return uploadSession.chunks.flat();
  }, [uploadSession]);
  const acceptedStagingReceipts = useMemo(() => {
    if (!verification) return undefined;
    return verification.files
      .filter((file) => file.accepted)
      .map((file) => file.staging_receipt);
  }, [verification]);
  const showRowActions =
    documentType === "visa" || documentType.startsWith("flight_ticket");
  const assignedDocumentIds = useMemo(
    () =>
      reviewRows.flatMap((row) =>
        reviewRowDocuments(row).map((document) => document.id),
      ),
    [reviewRows],
  );
  const visibleAssignedDocumentIds = useMemo(
    () =>
      visibleReviewRows.flatMap((row) =>
        reviewRowDocuments(row).map((document) => document.id),
      ),
    [visibleReviewRows],
  );
  const unmatchedDocumentIds = useMemo(
    () => (review.data?.unmatched_documents ?? []).map((document) => document.id),
    [review.data],
  );
  const selectableDocumentIds = useMemo(
    () => [...assignedDocumentIds, ...unmatchedDocumentIds],
    [assignedDocumentIds, unmatchedDocumentIds],
  );
  const assignedDocumentIdSet = useMemo(
    () => new Set(assignedDocumentIds),
    [assignedDocumentIds],
  );
  const visibleAssignedDocumentIdSet = useMemo(
    () => new Set(visibleAssignedDocumentIds),
    [visibleAssignedDocumentIds],
  );
  const unmatchedDocumentIdSet = useMemo(
    () => new Set(unmatchedDocumentIds),
    [unmatchedDocumentIds],
  );
  const selectableDocumentIdSet = useMemo(
    () => new Set(selectableDocumentIds),
    [selectableDocumentIds],
  );
  const activeSelectedDocumentIds = useMemo(
    () => selectedDocumentIds.filter((id) => selectableDocumentIdSet.has(id)),
    [selectableDocumentIdSet, selectedDocumentIds],
  );
  const activeSelectedDocumentIdSet = useMemo(
    () => new Set(activeSelectedDocumentIds),
    [activeSelectedDocumentIds],
  );
  const activeSelectedAssignedDocumentIds = useMemo(
    () => activeSelectedDocumentIds.filter((id) => assignedDocumentIdSet.has(id)),
    [activeSelectedDocumentIds, assignedDocumentIdSet],
  );
  const activeSelectedAssignedDocumentIdSet = useMemo(
    () => new Set(activeSelectedAssignedDocumentIds),
    [activeSelectedAssignedDocumentIds],
  );
  const activeSelectedUnmatchedDocumentIds = useMemo(
    () => activeSelectedDocumentIds.filter((id) => unmatchedDocumentIdSet.has(id)),
    [activeSelectedDocumentIds, unmatchedDocumentIdSet],
  );
  const activeSelectedUnmatchedDocumentIdSet = useMemo(
    () => new Set(activeSelectedUnmatchedDocumentIds),
    [activeSelectedUnmatchedDocumentIds],
  );
  const selectedAssignedPassengerCount = useMemo(
    () => reviewRows.filter((row) =>
      reviewRowDocuments(row).some((document) =>
        activeSelectedAssignedDocumentIdSet.has(document.id),
      ),
    ).length,
    [activeSelectedAssignedDocumentIdSet, reviewRows],
  );
  const allVisibleAssignmentsSelected =
    visibleAssignedDocumentIds.length > 0 &&
    visibleAssignedDocumentIds.every((id) =>
      activeSelectedAssignedDocumentIdSet.has(id),
    );
  const removalDocumentIds =
    activeSelectedAssignedDocumentIds.length > 0
      ? activeSelectedAssignedDocumentIds
      : assignedDocumentIds;
  const removalPassengerCount =
    activeSelectedAssignedDocumentIds.length > 0
      ? selectedAssignedPassengerCount
      : reviewCounts.assigned;
  const pendingRemovalDocumentIdSet = useMemo(
    () => new Set(pendingRemovalDocumentIds ?? []),
    [pendingRemovalDocumentIds],
  );
  const pendingRemovalPassengerCount = useMemo(
    () => pendingRemovalDocumentIds
      ? reviewRows.filter((row) =>
          reviewRowDocuments(row).some((document) =>
            pendingRemovalDocumentIdSet.has(document.id),
          ),
        ).length
      : 0,
    [pendingRemovalDocumentIdSet, pendingRemovalDocumentIds, reviewRows],
  );
  const removalPending = deleteDocuments.isPending || unassignDocuments.isPending;

  const defaultDeliveryDocumentIds = useMemo(
    () =>
      (deliveryPreview.data?.recipients ?? [])
        .filter((row) => row.eligible && row.document_id)
        .map((row) => row.document_id as string),
    [deliveryPreview.data],
  );
  const activeDeliveryDocumentIds =
    deliveryDocumentIds ?? defaultDeliveryDocumentIds;
  const activeDeliveryMessageContent1 =
    deliveryMessageContent1 ?? deliveryPreview.data?.message_content_1 ?? "";
  const activeDeliveryMessageContent2 =
    deliveryMessageContent2 ?? deliveryPreview.data?.message_content_2 ?? "";

  const resetSelection = (files: File[]) => {
    setSelectedFiles(files);
    setVerification(null);
    setUploadSession(null);
    setSelectionError(null);
    setProgressDetail(null);
    setProgress(0);
    setPhase("idle");
  };

  const checkDocuments = () => {
    if (selectedFiles.length === 0) return;
    setUploadSession(null);
    setSelectionError(null);
    setPhase("checking");
    setProgress(0);
    verify.mutate({
      files: selectedFiles,
      onProgress: (value) => {
        setProgressDetail(value);
        setProgress(value.percent);
      },
    }, {
      onSuccess: (data) => {
        setVerification(data.verification);
        setUploadSession(data.uploadSession);
        setProgress(100);
        setPhase("idle");
      },
      onError: () => {
        setPhase("idle");
      },
    });
  };

  const startUpload = () => {
    if (acceptedFiles.length === 0) return;
    if (hasIncompleteUploads && !canResumeCurrentUpload) {
      setSelectionError(
        "Discard the incomplete upload before starting another PDF upload.",
      );
      return;
    }
    const activeSession = uploadSession;
    if (!activeSession) {
      setSelectionError("Check the selected PDFs again before uploading them.");
      return;
    }
    setSelectionError(null);
    setPhase("uploading");
    setProgress(0);
    upload.mutate(
      {
        files: acceptedFiles,
        stagingReceipts: acceptedStagingReceipts,
        session: activeSession,
        onProgress: (value) => {
          setPhase("uploading");
          setProgressDetail(value);
          setProgress(value.percent);
        },
      },
      {
        onSuccess: () => {
          setSelectedFiles([]);
          setVerification(null);
          setUploadSession(null);
          setProgressDetail(null);
          setProgress(100);
          setPhase("idle");
        },
        onError: () => {
          setPhase("idle");
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        eyebrow="Group document workspace"
        title={group ? `${group.group_name} Documents` : "Group Documents"}
        description="Validate uploaded files, resolve passenger matching exceptions, save the reviewed roster, and control delivery from one group context."
        icon={LaneIcon}
        accent="cyan"
        context={(
          <>
            <WorkspaceHeaderContext icon={LaneIcon}>
              {lane.workflowLabel} workflow
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={CheckCircle2}>
              {assignedPassengerCount.toLocaleString()} of {(group?.total_passengers ?? reviewCounts.all).toLocaleString()} assigned
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={lane.category === "visa"
              ? ROUTES.dashboard.documentDistributionVisa
              : ROUTES.dashboard.documentDistributionFlightTickets}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {lane.category === "visa" ? "Visa Groups" : "Flight-Ticket Groups"}
          </IntentPrefetchLink>
        )}
      />

      {lane.category === "flight_tickets" && (
        <FlightTicketLaneNavigation
          groupId={groupId}
          group={group}
          lane={lane}
          operationPending={documentTypeOperationPending}
          hasUncommittedSelection={hasUncommittedSelection}
        />
      )}

      <DocumentUploadPanel
        lane={lane}
        passengerCount={review.data?.review_rows.length ?? 0}
        selectedFileCount={selectedFiles.length}
        acceptedFileCount={acceptedFiles.length}
        verificationReady={Boolean(verification)}
        hasIncompleteUploads={hasIncompleteUploads}
        canResumeCurrentUpload={canResumeCurrentUpload}
        processingUploadCount={processingUploadIds.length}
        uploadPending={upload.isPending}
        verifyPending={verify.isPending}
        abortPending={abortUploads.isPending}
        onFilesSelected={resetSelection}
        onCheck={checkDocuments}
        onUpload={startUpload}
        onDiscardIncomplete={() => setIsAbortUploadDialogOpen(true)}
      />

      {(upload.isPending || phase !== "idle" || upload.error || selectionError || verify.error || reupload.error || deleteDocuments.error || unassignDocuments.error || verification) && (
      <Card>
        <CardContent className="space-y-4 p-5">
          {(upload.isPending || phase !== "idle") && (
            <div className="space-y-2 rounded-lg border border-blue-100 bg-blue-50 p-3">
              <div className="flex items-center justify-between text-sm font-medium text-blue-900">
                <span>
                  {phase === "checking"
                    ? progressDetail?.phase === "processing"
                      ? "Checking PDFs in parallel"
                      : "Preparing parallel PDF checks"
                    : progressDetail?.phase === "processing"
                      ? "Matching and saving PDFs"
                      : "Uploading accepted PDFs"}
                  {progressDetail
                    ? ` — ${progressDetail.completedFiles}/${progressDetail.totalFiles} complete`
                    : ""}
                </span>
                <span>{progress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white">
                <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {upload.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {upload.error.message}
              {progressDetail && progressDetail.completedFiles > 0
                ? ` ${progressDetail.completedFiles} of ${progressDetail.totalFiles} PDFs are safely committed; click Upload Accepted again to resume.`
                : ""}
            </div>
          )}

          {selectionError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {selectionError}
            </div>
          )}

          {verify.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {verify.error.message}
            </div>
          )}

          {reupload.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {reupload.error.message}
            </div>
          )}

          {deleteDocuments.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {deleteDocuments.error.message}
            </div>
          )}

          {unassignDocuments.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {unassignDocuments.error.message}
            </div>
          )}

          {verification && (
            <VerificationPanel verification={verification} />
          )}
        </CardContent>
      </Card>
      )}

      {review.isLoading ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="flex flex-col gap-3 border-b border-slate-100 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-900">Review Matches</h2>
                <p className="mt-1 text-sm text-slate-500">
                  {assignedFileCount} files assigned across {assignedPassengerCount} passengers, {needsAssignmentCount} need assignment, {review.data?.rejected_count ?? 0} rejected.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="danger"
                  disabled={removalDocumentIds.length === 0 || removalPending}
                  isLoading={removalPending && pendingRemovalDocumentIds !== null}
                  onClick={() => setPendingRemovalDocumentIds(removalDocumentIds)}
                >
                  <Trash2 className="h-4 w-4" />
                  {activeSelectedAssignedDocumentIds.length > 0
                    ? `Remove assignments (${removalPassengerCount})`
                    : `Remove all assigned (${removalPassengerCount})`}
                </Button>
                {activeSelectedUnmatchedDocumentIds.length > 0 && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={removalPending}
                    isLoading={deleteDocuments.isPending && pendingRemovalDocumentIds === null}
                    onClick={() =>
                      deleteDocuments.mutate(activeSelectedUnmatchedDocumentIds, {
                        onSuccess: () => {
                          setSelectedDocumentIds((current) =>
                            current.filter(
                              (id) => !activeSelectedUnmatchedDocumentIdSet.has(id),
                            ),
                          );
                        },
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete unassigned files ({activeSelectedUnmatchedDocumentIds.length})
                  </Button>
                )}
                <Button
                  type="button"
                  disabled={!review.data?.batch_id || review.data.status === "saved" || hasIncompleteUploads}
                  isLoading={save.isPending}
                  onClick={() => review.data?.batch_id && save.mutate(review.data.batch_id)}
                >
                  <Save className="h-4 w-4" />
                  {review.data?.status === "saved" ? "Saved" : "Save List"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!review.data?.batch_id || review.data.status !== "saved"}
                  onClick={() => {
                    setDeliveryDocumentIds(null);
                    setDeliveryResendDocumentIds([]);
                    setDeliveryMessageContent1(null);
                    setDeliveryMessageContent2(null);
                    setDeliveryFeedback(null);
                    setIsSendPreviewOpen(true);
                  }}
                >
                  <Send className="h-4 w-4" />
                  Send WhatsApp Broadcast
                </Button>
              </div>
            </div>

            {review.data && physicalFileCount > 0 && (
              <div className={`border-b p-5 ${needsAssignmentCount > 0 ? "border-amber-200 bg-amber-50/70" : "border-emerald-100 bg-emerald-50/60"}`}>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 className={`flex items-center gap-2 text-sm font-semibold ${needsAssignmentCount > 0 ? "text-amber-950" : "text-emerald-900"}`}>
                      {needsAssignmentCount > 0 ? <FileQuestion className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                      Needs assignment ({needsAssignmentCount})
                    </h3>
                    <p className={`mt-1 text-sm ${needsAssignmentCount > 0 ? "text-amber-800" : "text-emerald-800"}`}>
                      {assignedFileCount} verified files are assigned across {assignedPassengerCount} passengers.
                      {assignedFileCount !== assignedPassengerCount
                        ? " Multiple files can be correctly assigned to the same passenger."
                        : ""}
                    </p>
                  </div>
                  <div className="text-xs font-medium text-slate-600">
                    {physicalFileCount} verified files stored
                  </div>
                </div>

                {assignmentIssues.length > 0 ? (
                  <div className="mt-3 max-h-64 space-y-2 overflow-auto">
                    {assignmentIssues.map((issue) => (
                      <div key={issue.document_id} className="flex items-start gap-3 rounded-lg border border-amber-200 bg-white px-3 py-2.5 text-sm">
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4 rounded border-amber-300"
                          aria-label={`Select ${issue.original_filename}`}
                          checked={activeSelectedDocumentIdSet.has(issue.document_id)}
                          disabled={removalPending}
                          onChange={(event) => {
                            setSelectedDocumentIds((current) =>
                              event.target.checked
                                ? Array.from(new Set([...current, issue.document_id]))
                                : current.filter((id) => id !== issue.document_id),
                            );
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          {issue.url ? (
                            <a href={issue.url} target="_blank" rel="noreferrer" className="break-all font-semibold text-amber-950 hover:underline">
                              {issue.original_filename}
                            </a>
                          ) : (
                            <div className="break-all font-semibold text-amber-950">{issue.original_filename}</div>
                          )}
                          <div className="mt-1 text-amber-800">{issue.reason}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm text-emerald-800">
                    Every verified stored file has a passenger assignment.
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
              {([
                ["all", "All", reviewCounts.all],
                ["assigned", "Assigned", reviewCounts.assigned],
                ["missing", "Missing", reviewCounts.missing],
                ["sent", "Sent", reviewCounts.sent],
                ["not_sent", "Not sent", reviewCounts.not_sent],
              ] as Array<[ReviewFilter, string, number]>).map(([value, label, count]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setReviewFilter(value)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                    reviewFilter === value
                      ? "border-blue-600 bg-blue-600 text-white"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                  }`}
                >
                  {label} ({count})
                </button>
              ))}
              <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-3 sm:w-auto">
                {activeSelectedAssignedDocumentIds.length > 0 && (
                  <button
                    type="button"
                    className="text-xs font-medium text-blue-700 hover:underline"
                    onClick={() =>
                      setSelectedDocumentIds((current) =>
                        current.filter(
                          (id) => !activeSelectedAssignedDocumentIdSet.has(id),
                        ),
                      )
                    }
                  >
                    Clear selected assignments
                  </button>
                )}
                <label className="relative w-full sm:w-64">
                  <span className="sr-only">Search passenger name</span>
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type="search"
                    value={reviewSearchQuery}
                    onChange={(event) => setReviewSearchQuery(event.target.value)}
                    placeholder="Search passenger name"
                    className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  />
                </label>
              </div>
            </div>

            <div className="w-full overflow-visible">
              <table className="w-full table-fixed text-left text-sm">
                <caption className="sr-only">Assigned passenger documents</caption>
                <thead>
                  <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                    <th scope="col" className="w-12 px-3 py-4">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300"
                        aria-label="Select all visible assigned passengers"
                        checked={allVisibleAssignmentsSelected}
                        disabled={visibleAssignedDocumentIds.length === 0 || removalPending}
                        onChange={(event) => {
                          setSelectedDocumentIds((current) => {
                            const withoutVisible = current.filter(
                              (id) => !visibleAssignedDocumentIdSet.has(id),
                            );
                            return event.target.checked
                              ? Array.from(new Set([...withoutVisible, ...visibleAssignedDocumentIds]))
                              : withoutVisible;
                          });
                        }}
                      />
                    </th>
                    <th scope="col" className="w-[18%] px-3 py-4">Passenger</th>
                    <th scope="col" className="w-[11%] px-3 py-4">Passport</th>
                    <th scope="col" className="w-[25%] px-3 py-4">Document</th>
                    <th scope="col" className="w-[10%] px-3 py-4">Confidence</th>
                    <th scope="col" className="w-[12%] px-3 py-4">Status</th>
                    <th scope="col" className="w-[19%] px-3 py-4">Sent</th>
                    {showRowActions && <th scope="col" className="w-16 px-3 py-4 text-right">Action</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {visibleReviewRows.map((row) => {
                    const documents = reviewRowDocuments(row);
                    const rowDocumentIds = documents.map((document) => document.id);
                    const rowDocumentIdSet = new Set(rowDocumentIds);
                    const rowAssignmentsSelected =
                      rowDocumentIds.length > 0 &&
                      rowDocumentIds.every((id) =>
                        activeSelectedAssignedDocumentIdSet.has(id),
                      );
                    return (
                    <tr key={row.passenger_id}>
                      <td className="px-3 py-4 align-top">
                        {documents.length > 0 ? (
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-slate-300"
                            aria-label={`Select all assignments for ${row.passenger_name}`}
                            checked={rowAssignmentsSelected}
                            disabled={removalPending}
                            onChange={(event) => {
                              setSelectedDocumentIds((current) => {
                                const withoutRow = current.filter(
                                  (id) => !rowDocumentIdSet.has(id),
                                );
                                return event.target.checked
                                  ? Array.from(new Set([...withoutRow, ...rowDocumentIds]))
                                  : withoutRow;
                              });
                            }}
                          />
                        ) : (
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-slate-300"
                            aria-label={`No document available for ${row.passenger_name}`}
                            disabled
                          />
                        )}
                      </td>
                      <td className="min-w-0 px-3 py-4 align-top">
                        <div className="break-words font-semibold text-slate-900">{row.passenger_name}</div>
                        <div className="mt-1 text-xs text-slate-500">{row.departure_city || "No departure city"}</div>
                        {documents.length > 1 && (
                          <Badge variant="outline" className="mt-2 whitespace-nowrap">
                            {documents.length} saved documents
                          </Badge>
                        )}
                      </td>
                      <td className="break-words px-3 py-4 align-top text-slate-700">{row.passport_number || "Not set"}</td>
                      <td className="min-w-0 px-3 py-4 align-top">
                        {documents.length > 0 ? (
                          <div className="divide-y divide-slate-100">
                            {documents.map((document) => (
                              <div key={document.id} className="flex min-h-16 flex-col justify-center py-2 first:pt-0 last:pb-0">
                                <a href={document.url ?? "#"} target="_blank" rel="noreferrer" className="break-words font-medium text-blue-700 hover:underline">
                                  {document.original_filename}
                                </a>
                                <div className="mt-1 text-xs text-slate-500">
                                  {document.source === "email" ? "Saved from email" : "Manual upload"}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400">Empty</span>
                        )}
                      </td>
                      <td className="px-3 py-4 align-top text-slate-700">
                        {documents.length > 0 ? (
                          <div className="divide-y divide-slate-100">
                            {documents.map((document) => (
                              <div key={document.id} className="flex min-h-16 items-center py-2 first:pt-0 last:pb-0">
                                {formatConfidence(document.match_confidence)}
                              </div>
                            ))}
                          </div>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-3 py-4 align-top">
                        {documents.length > 0 ? (
                          <div className="divide-y divide-slate-100">
                            {documents.map((document) => (
                              <div key={document.id} className="flex min-h-16 items-center py-2 first:pt-0 last:pb-0">
                                <MatchBadge status={document.match_status} />
                              </div>
                            ))}
                          </div>
                        ) : (
                          <MatchBadge status="no_document" />
                        )}
                      </td>
                      <td className="min-w-0 px-3 py-4 align-top">
                        {documents.length > 0 ? (
                          <div className="divide-y divide-slate-100">
                            {documents.map((document) => (
                              <div key={document.id} className="flex min-h-16 items-center py-2 first:pt-0 last:pb-0">
                                <DocumentSentStatus
                                  status={document.delivery_status}
                                  sentTo={document.sent_to}
                                  sentAt={document.last_sent_at}
                                  canResend={document.can_resend}
                                  onResend={() => {
                                    setDeliveryDocumentIds([document.id]);
                                    setDeliveryResendDocumentIds([document.id]);
                                    setDeliveryMessageContent1(null);
                                    setDeliveryMessageContent2(null);
                                    setDeliveryFeedback(null);
                                    setIsSendPreviewOpen(true);
                                  }}
                                />
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400">&mdash;</span>
                        )}
                      </td>
                      {showRowActions && (
                        <td className="px-3 py-4 text-right align-top">
                          <DocumentRowActionMenu
                            row={row}
                            documents={documents}
                            documentType={documentType}
                            pending={reupload.isPending || removalPending}
                            onReupload={(file) => reupload.mutate({ passengerId: row.passenger_id, file })}
                            onRemoveAssignment={(documentId) =>
                              setPendingRemovalDocumentIds([documentId])
                            }
                          />
                        </td>
                      )}
                    </tr>
                    );
                  })}
                  {visibleReviewRows.length === 0 && (
                    <tr>
                      <td
                        colSpan={showRowActions ? 8 : 7}
                        className="px-5 py-10 text-center text-sm text-slate-500"
                      >
                        {reviewSearchQuery.trim()
                          ? "No passenger names match this search and filter."
                          : "No passengers match this filter."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {review.data && review.data.rejected_documents.length > 0 && (
              <div className="border-t border-slate-100 p-5">
                <h3 className="text-sm font-semibold text-slate-900">Rejected Files</h3>
                <div className="mt-3 grid gap-2">
                  {review.data.rejected_documents.map((file, index) => (
                    <div key={`${file.filename}:${index}`} className="flex items-center justify-between gap-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm">
                      <span className="font-medium text-red-950">{file.filename}</span>
                      <span className="text-red-700">{file.reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </CardContent>
        </Card>
      )}

      {pendingRemovalDocumentIds && (
        <RemoveAssignmentsDialog
          passengerCount={pendingRemovalPassengerCount}
          documentCount={pendingRemovalDocumentIds.length}
          pending={removalPending}
          error={unassignDocuments.error ?? deleteDocuments.error}
          onClose={() => {
            if (!removalPending) setPendingRemovalDocumentIds(null);
          }}
          onKeepFiles={() => {
            unassignDocuments.mutate(pendingRemovalDocumentIds, {
              onSuccess: () => {
                setSelectedDocumentIds((current) =>
                  current.filter((id) => !pendingRemovalDocumentIdSet.has(id)),
                );
                setPendingRemovalDocumentIds(null);
              },
            });
          }}
          onDeleteFiles={() => {
            deleteDocuments.mutate(pendingRemovalDocumentIds, {
              onSuccess: () => {
                setSelectedDocumentIds((current) =>
                  current.filter((id) => !pendingRemovalDocumentIdSet.has(id)),
                );
                setPendingRemovalDocumentIds(null);
              },
            });
          }}
        />
      )}

      {isAbortUploadDialogOpen && hasIncompleteUploads && (
        <AbortIncompleteUploadDialog
          uploadCount={processingUploadIds.length}
          pending={abortUploads.isPending}
          error={abortUploads.error}
          onClose={() => {
            if (!abortUploads.isPending) setIsAbortUploadDialogOpen(false);
          }}
          onConfirm={() => {
            abortUploads.mutate(processingUploadIds, {
              onSuccess: () => {
                setSelectedFiles([]);
                setVerification(null);
                setUploadSession(null);
                setSelectionError(null);
                setProgressDetail(null);
                setProgress(0);
                setPhase("idle");
                setIsAbortUploadDialogOpen(false);
              },
            });
          }}
        />
      )}

      {deliveryFeedback && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {deliveryFeedback}
        </div>
      )}

      {isSendPreviewOpen && (
        <DocumentDeliveryPreviewDialog
          preview={deliveryPreview.data}
          loading={deliveryPreview.isLoading}
          loadError={deliveryPreview.error}
          selectedDocumentIds={activeDeliveryDocumentIds}
          resendDocumentIds={deliveryResendDocumentIds}
          sending={sendDocuments.isPending}
          sendError={sendDocuments.error}
          messageContent1={activeDeliveryMessageContent1}
          messageContent2={activeDeliveryMessageContent2}
          onMessageContent1Change={setDeliveryMessageContent1}
          onMessageContent2Change={setDeliveryMessageContent2}
          onToggleDocument={(documentId) => {
            setDeliveryDocumentIds((current) => {
              const selection = current ?? defaultDeliveryDocumentIds;
              return selection.includes(documentId)
                ? selection.filter((id) => id !== documentId)
                : [...selection, documentId];
            });
            setDeliveryResendDocumentIds((current) =>
              current.filter((id) => id !== documentId),
            );
          }}
          onToggleResend={(documentId) => {
            setDeliveryResendDocumentIds((current) => {
              const removing = current.includes(documentId);
              setDeliveryDocumentIds((selected) => {
                const selection = selected ?? defaultDeliveryDocumentIds;
                return removing
                  ? selection.filter((id) => id !== documentId)
                  : Array.from(new Set([...selection, documentId]));
              });
              return removing
                ? current.filter((id) => id !== documentId)
                : [...current, documentId];
            });
          }}
          onClose={() => {
            if (!sendDocuments.isPending) {
              setIsSendPreviewOpen(false);
            }
          }}
          onSend={() => {
            const batchId = deliveryPreview.data?.batch_id;
            if (!batchId) return;
            sendDocuments.mutate(
              {
                batchId,
                documentIds: activeDeliveryDocumentIds,
                resendDocumentIds: deliveryResendDocumentIds,
                messageContent1: activeDeliveryMessageContent1.trim(),
                messageContent2: activeDeliveryMessageContent2.trim(),
              },
              {
                onSuccess: (result) => {
                  setDeliveryFeedback(result.message);
                  setIsSendPreviewOpen(false);
                  setDeliveryDocumentIds(null);
                  setDeliveryResendDocumentIds([]);
                },
              },
            );
          }}
        />
      )}
    </div>
  );
}
