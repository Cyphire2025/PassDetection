"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  Plane,
} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceHeaderContext,
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  SENSITIVE_STATE_RESET_EVENT,
  subscribeToSessionResets,
} from "@/features/auth/services/session-state";
import {
  WhatsAppActivityInline,
  useWhatsAppActivityTracker,
} from "@/features/whatsapp/components/whatsapp-activity-tracker";
import type { DocumentVerificationResult } from "@/types/document-distribution.types";
import {
  useAbortDistributionUploads,
  useDeleteDistributionDocuments,
  useDocumentDeliveryPreview,
  useDocumentGroups,
  useDocumentReview,
  useExportDocumentAssignments,
  useReuploadPassengerDocument,
  useSaveDocumentBatch,
  useSendDocumentWhatsAppBroadcast,
  useUnassignDistributionDocuments,
  useUploadDistributionDocuments,
  useVerifyDistributionDocuments,
} from "../hooks/use-document-distribution";
import {
  type DocumentUploadProgress,
  type DocumentStagingManifest,
} from "../services/document-upload-batching";
import {
  clearDocumentUploadRecovery,
  persistDocumentUploadRecovery,
  readDocumentUploadRecovery,
} from "../services/document-upload-recovery";
import {
  type DocumentDistributionLane,
} from "../config/document-distribution-lanes";
import {
  countPassengersForDocuments,
  createActiveDocumentSelection,
  createDocumentReviewModel,
  documentIdsForRows,
  eligibleDeliveryDocumentIds,
  filterDocumentReviewRows,
  type ReviewFilter,
  updateSelectedDocumentIds,
} from "./document-workspace-model";
import {
  DocumentUploadPanel,
  type DocumentUploadPhase,
} from "./document-upload-panel";

function DialogLoadingFallback() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div role="status" className="rounded-xl bg-white px-5 py-4 text-sm font-medium text-slate-700 shadow-xl">
        Loading secure dialog…
      </div>
    </div>
  );
}

const AbortIncompleteUploadDialog = dynamic(
  () => import("./document-workspace-dialogs").then((module) => module.AbortIncompleteUploadDialog),
  { loading: DialogLoadingFallback },
);
const DocumentDeliveryPreviewDialog = dynamic(
  () => import("./document-workspace-dialogs").then((module) => module.DocumentDeliveryPreviewDialog),
  { loading: DialogLoadingFallback },
);
const RemoveAssignmentsDialog = dynamic(
  () => import("./document-workspace-dialogs").then((module) => module.RemoveAssignmentsDialog),
  { loading: DialogLoadingFallback },
);
const DocumentWorkspaceUploadStatus = dynamic(
  () => import("./document-workspace-upload-status").then((module) => module.DocumentWorkspaceUploadStatus),
  { loading: () => <Skeleton className="h-32 rounded-xl" /> },
);
const DocumentWorkspaceReviewControls = dynamic(
  () => import("./document-workspace-review-controls").then((module) => module.DocumentWorkspaceReviewControls),
  { loading: () => <Skeleton className="h-40 rounded-xl" /> },
);
const DocumentWorkspaceReviewRows = dynamic(
  () => import("./document-workspace-review-rows").then((module) => module.DocumentWorkspaceReviewRows),
  {
    loading: () => (
      <tbody>
        <tr>
          <td colSpan={8} className="px-5 py-10 text-center text-sm text-slate-500" role="status">
            Loading passenger documents…
          </td>
        </tr>
      </tbody>
    ),
  },
);
const FlightTicketLaneNavigation = dynamic(
  () => import("./flight-ticket-lane-navigation").then((module) => module.FlightTicketLaneNavigation),
  { loading: () => <Skeleton className="h-24 rounded-xl" /> },
);

export function DocumentWorkspace({
  groupId,
  lane,
}: {
  groupId: string;
  lane: DocumentDistributionLane;
}) {
  const { registerActivity } = useWhatsAppActivityTracker();
  const documentType = lane.documentType;
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [verification, setVerification] = useState<DocumentVerificationResult | null>(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [reviewSearchQuery, setReviewSearchQuery] = useState("");
  const [pendingRemovalDocumentIds, setPendingRemovalDocumentIds] = useState<string[] | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressDetail, setProgressDetail] = useState<DocumentUploadProgress | null>(null);
  const [stagingManifest, setStagingManifest] = useState<DocumentStagingManifest | null>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
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
  const exportAssignments = useExportDocumentAssignments(
    groupId,
    documentType,
    group?.group_name,
  );
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
    selectedFiles.length > 0 || verification !== null || stagingManifest !== null;
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
  const reviewModel = useMemo(
    () => createDocumentReviewModel(review.data),
    [review.data],
  );
  const reviewCounts = reviewModel.counts;
  const assignmentIssues = reviewModel.assignmentIssues;
  const assignedDocumentIds = reviewModel.assignedDocumentIds;
  const visibleReviewRows = useMemo(
    () => filterDocumentReviewRows(reviewModel, reviewFilter, reviewSearchQuery),
    [reviewFilter, reviewModel, reviewSearchQuery],
  );
  const visibleAssignedDocumentIds = useMemo(
    () => documentIdsForRows(
      visibleReviewRows,
      reviewModel.documentsByPassengerId,
    ),
    [reviewModel.documentsByPassengerId, visibleReviewRows],
  );
  const activeSelection = useMemo(
    () => createActiveDocumentSelection(selectedDocumentIds, reviewModel),
    [reviewModel, selectedDocumentIds],
  );
  const activeSelectedDocumentIdSet = activeSelection.documentIdSet;
  const activeSelectedAssignedDocumentIds = activeSelection.assignedDocumentIds;
  const activeSelectedAssignedDocumentIdSet = activeSelection.assignedDocumentIdSet;
  const activeSelectedUnmatchedDocumentIds = activeSelection.unmatchedDocumentIds;
  const activeSelectedUnmatchedDocumentIdSet = activeSelection.unmatchedDocumentIdSet;
  const selectedAssignedPassengerCount = useMemo(
    () => countPassengersForDocuments(
      reviewModel,
      activeSelection.assignedDocumentIdSet,
    ),
    [activeSelection.assignedDocumentIdSet, reviewModel],
  );
  const allVisibleAssignmentsSelected =
    visibleAssignedDocumentIds.length > 0
    && visibleAssignedDocumentIds.every((id) =>
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
      ? countPassengersForDocuments(reviewModel, pendingRemovalDocumentIdSet)
      : 0,
    [pendingRemovalDocumentIdSet, pendingRemovalDocumentIds, reviewModel],
  );
  const removalPending = deleteDocuments.isPending || unassignDocuments.isPending;
  const physicalFileCount =
    review.data?.physical_file_count ?? review.data?.uploaded_count ?? 0;
  const assignedFileCount =
    review.data?.assigned_file_count
    ?? Math.max(physicalFileCount - assignmentIssues.length, 0);
  const assignedPassengerCount =
    review.data?.assigned_passenger_count ?? reviewCounts.assigned;
  const needsAssignmentCount =
    review.data?.needs_assignment_count ?? assignmentIssues.length;
  const acceptedFileCount = stagingManifest?.totalFiles ?? 0;
  const showRowActions =
    documentType === "visa" || documentType.startsWith("flight_ticket");
  const defaultDeliveryDocumentIds = useMemo(
    () => eligibleDeliveryDocumentIds(deliveryPreview.data),
    [deliveryPreview.data],
  );
  const activeDeliveryDocumentIds =
    deliveryDocumentIds ?? defaultDeliveryDocumentIds;
  const activeDeliveryMessageContent1 =
    deliveryMessageContent1 ?? deliveryPreview.data?.message_content_1 ?? "";
  const activeDeliveryMessageContent2 =
    deliveryMessageContent2 ?? deliveryPreview.data?.message_content_2 ?? "";

  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      if (!mounted) return;
      const recovered = readDocumentUploadRecovery(groupId, documentType);
      setVerification(recovered?.verification ?? null);
      setStagingManifest(recovered?.manifest ?? null);
      setSelectedFiles([]);
    });

    const abortSensitiveWork = () => {
      activeRequestRef.current?.abort("session-reset");
      activeRequestRef.current = null;
      setSelectedFiles([]);
      setVerification(null);
      setStagingManifest(null);
      setProgressDetail(null);
      setProgress(0);
      setPhase("idle");
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
  }, [documentType, groupId]);

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
    activeRequestRef.current?.abort("document-selection-replaced");
    activeRequestRef.current = null;
    clearDocumentUploadRecovery(groupId, documentType);
    setSelectedFiles(files);
    setVerification(null);
    setStagingManifest(null);
    setSelectionError(null);
    setProgressDetail(null);
    setProgress(0);
    setPhase("idle");
  };

  const checkDocuments = () => {
    if (selectedFiles.length === 0) return;
    const controller = beginAbortableRequest();
    clearDocumentUploadRecovery(groupId, documentType);
    setStagingManifest(null);
    setSelectionError(null);
    setPhase("checking");
    setProgress(0);
    verify.mutate({
      files: selectedFiles,
      signal: controller.signal,
      onProgress: (value) => {
        setProgressDetail(value);
        setProgress(value.percent);
      },
    }, {
      onSuccess: (data) => {
        persistDocumentUploadRecovery(groupId, documentType, {
          verification: data.verification,
          manifest: data.stagingManifest,
        });
        // Verification has transferred durable ownership to encrypted staging;
        // do not keep the original browser File objects alive in React state.
        setSelectedFiles([]);
        setVerification(data.verification);
        setStagingManifest(data.stagingManifest);
        setProgress(100);
        setPhase("idle");
      },
      onError: () => {
        setPhase("idle");
      },
      onSettled: () => releaseRequest(controller),
    });
  };

  const startUpload = () => {
    if (acceptedFileCount === 0) return;
    if (hasIncompleteUploads && !canResumeCurrentUpload) {
      setSelectionError(
        "Discard the incomplete upload before starting another PDF upload.",
      );
      return;
    }
    const activeManifest = stagingManifest;
    const activeVerification = verification;
    if (!activeManifest || !activeVerification) {
      setSelectionError("Check the selected PDFs again before uploading them.");
      return;
    }
    const controller = beginAbortableRequest();
    setSelectionError(null);
    setPhase("uploading");
    setProgress(0);
    upload.mutate(
      {
        manifest: activeManifest,
        signal: controller.signal,
        onManifestChange: (manifest) => {
          setStagingManifest(manifest);
          persistDocumentUploadRecovery(groupId, documentType, {
            verification: activeVerification,
            manifest,
          });
        },
        onProgress: (value) => {
          setPhase("uploading");
          setProgressDetail(value);
          setProgress(value.percent);
        },
      },
      {
        onSuccess: () => {
          clearDocumentUploadRecovery(groupId, documentType);
          setSelectedFiles([]);
          setVerification(null);
          setStagingManifest(null);
          setProgressDetail(null);
          setProgress(100);
          setPhase("idle");
        },
        onError: () => {
          setPhase("idle");
        },
        onSettled: () => releaseRequest(controller),
      },
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title={group ? `${group.group_name} Documents` : "Group Documents"}
        description="Upload PDFs, confirm passenger matches, and save the document list before sending."
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

      <WhatsAppActivityInline />

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
        acceptedFileCount={acceptedFileCount}
        verificationReady={Boolean(verification && stagingManifest)}
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
        <DocumentWorkspaceUploadStatus
          phase={phase}
          progress={progress}
          progressDetail={progressDetail}
          uploadPending={upload.isPending}
          uploadError={upload.error}
          selectionError={selectionError}
          verifyError={verify.error}
          reuploadError={reupload.error}
          deleteError={deleteDocuments.error}
          unassignError={unassignDocuments.error}
          verification={verification}
        />
      )}

      {review.isLoading ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <DocumentWorkspaceReviewControls
              assignedFileCount={assignedFileCount}
              assignedPassengerCount={assignedPassengerCount}
              needsAssignmentCount={needsAssignmentCount}
              rejectedCount={review.data?.rejected_count ?? 0}
              removalDocumentCount={removalDocumentIds.length}
              removalPassengerCount={removalPassengerCount}
              selectedAssignedDocumentCount={activeSelectedAssignedDocumentIds.length}
              selectedUnmatchedDocumentCount={activeSelectedUnmatchedDocumentIds.length}
              removalPending={removalPending}
              removalConfirmationPending={removalPending && pendingRemovalDocumentIds !== null}
              deleteUnassignedPending={deleteDocuments.isPending && pendingRemovalDocumentIds === null}
              saveDisabled={!review.data?.batch_id || review.data.status === "saved" || hasIncompleteUploads}
              savePending={save.isPending}
              saved={review.data?.status === "saved"}
              deliveryDisabled={!review.data?.batch_id || review.data.status !== "saved"}
              exportPending={exportAssignments.isPending}
              exportError={exportAssignments.isError}
              hasReviewData={Boolean(review.data)}
              physicalFileCount={physicalFileCount}
              assignmentIssues={assignmentIssues}
              selectedDocumentIdSet={activeSelectedDocumentIdSet}
              reviewCounts={reviewCounts}
              reviewFilter={reviewFilter}
              searchQuery={reviewSearchQuery}
              onRequestRemoval={() => setPendingRemovalDocumentIds(removalDocumentIds)}
              onDeleteUnassigned={() =>
                deleteDocuments.mutate(activeSelectedUnmatchedDocumentIds, {
                  onSuccess: () => {
                    setSelectedDocumentIds((current) =>
                      updateSelectedDocumentIds(
                        current,
                        activeSelectedUnmatchedDocumentIdSet,
                        false,
                      ),
                    );
                  },
                })
              }
              onSave={() =>
                review.data?.batch_id && save.mutate(review.data.batch_id)
              }
              onOpenDelivery={() => {
                setDeliveryDocumentIds(null);
                setDeliveryResendDocumentIds([]);
                setDeliveryMessageContent1(null);
                setDeliveryMessageContent2(null);
                setDeliveryFeedback(null);
                setIsSendPreviewOpen(true);
              }}
              onExport={() => {
                exportAssignments.reset();
                exportAssignments.mutate({
                  filter: reviewFilter,
                  search: reviewSearchQuery,
                });
              }}
              onToggleIssue={(documentId, selected) =>
                setSelectedDocumentIds((current) =>
                  updateSelectedDocumentIds(current, [documentId], selected),
                )
              }
              onReviewFilterChange={setReviewFilter}
              onClearSelectedAssignments={() =>
                setSelectedDocumentIds((current) =>
                  updateSelectedDocumentIds(
                    current,
                    activeSelectedAssignedDocumentIdSet,
                    false,
                  ),
                )
              }
              onSearchQueryChange={setReviewSearchQuery}
            />

            <div
              className="w-full overflow-x-auto overscroll-x-contain"
              role="region"
              aria-label="Passenger document review table"
              tabIndex={0}
            >
              <table className="w-full table-fixed min-w-[1120px] text-left text-sm">
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
                        onChange={(event) =>
                          setSelectedDocumentIds((current) =>
                            updateSelectedDocumentIds(
                              current,
                              visibleAssignedDocumentIds,
                              event.target.checked,
                            ),
                          )
                        }
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
                <DocumentWorkspaceReviewRows
                  rows={visibleReviewRows}
                  documentsByPassengerId={reviewModel.documentsByPassengerId}
                  activeSelectedAssignedDocumentIdSet={activeSelectedAssignedDocumentIdSet}
                  documentType={documentType}
                  showRowActions={showRowActions}
                  removalPending={removalPending}
                  reuploadPending={reupload.isPending}
                  searchQuery={reviewSearchQuery}
                  onToggleRowDocuments={(documentIds, selected) =>
                    setSelectedDocumentIds((current) =>
                      updateSelectedDocumentIds(current, documentIds, selected),
                    )
                  }
                  onReupload={(passengerId, file) =>
                    reupload.mutate({ passengerId, file })
                  }
                  onRemoveAssignment={(documentId) =>
                    setPendingRemovalDocumentIds([documentId])
                  }
                  onResend={(documentId) => {
                    setDeliveryDocumentIds([documentId]);
                    setDeliveryResendDocumentIds([documentId]);
                    setDeliveryMessageContent1(null);
                    setDeliveryMessageContent2(null);
                    setDeliveryFeedback(null);
                    setIsSendPreviewOpen(true);
                  }}
                />
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
                  updateSelectedDocumentIds(
                    current,
                    pendingRemovalDocumentIdSet,
                    false,
                  ),
                );
                setPendingRemovalDocumentIds(null);
              },
            });
          }}
          onDeleteFiles={() => {
            deleteDocuments.mutate(pendingRemovalDocumentIds, {
              onSuccess: () => {
                setSelectedDocumentIds((current) =>
                  updateSelectedDocumentIds(
                    current,
                    pendingRemovalDocumentIdSet,
                    false,
                  ),
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
                clearDocumentUploadRecovery(groupId, documentType);
                setSelectedFiles([]);
                setVerification(null);
                setStagingManifest(null);
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
              return updateSelectedDocumentIds(
                selection,
                [documentId],
                !selection.includes(documentId),
              );
            });
            setDeliveryResendDocumentIds((current) =>
              updateSelectedDocumentIds(current, [documentId], false),
            );
          }}
          onToggleResend={(documentId) => {
            setDeliveryResendDocumentIds((current) => {
              const removing = current.includes(documentId);
              setDeliveryDocumentIds((selected) => {
                const selection = selected ?? defaultDeliveryDocumentIds;
                return updateSelectedDocumentIds(
                  selection,
                  [documentId],
                  !removing,
                );
              });
              return updateSelectedDocumentIds(
                current,
                [documentId],
                !removing,
              );
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
                  if (result.send_batch_id) {
                    registerActivity({
                      id: result.send_batch_id,
                      kind: "document",
                      startedAt: Date.now(),
                      title: `${lane.title} broadcast`,
                      contextLabel: group?.group_name ?? "Document distribution",
                      sourceGroupId: groupId,
                      documentType,
                      total: result.queued_count,
                      queued: result.queued_count,
                      sent: 0,
                      failed: 0,
                      deliveryUnknown: 0,
                    });
                  }
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
