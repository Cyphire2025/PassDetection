"use client";
import { clearDocumentUploadRecovery } from "../services/document-upload-recovery";
import { ManualPassengerDocumentDialog } from "./manual-passenger-document-dialog";
import { updateSelectedDocumentIds } from "./document-workspace-model";
import { AbortIncompleteUploadDialog, DocumentDeliveryPreviewDialog, RemoveAssignmentsDialog } from "./document-workspace-bindings";
import type { DocumentWorkspaceController } from "../hooks/use-document-workspace";

export function DocumentWorkspaceActions({ controller }: { controller: DocumentWorkspaceController }) {
  const {
    groupId, documentType, abortUploads,
    manualUpload, deleteDocuments, unassignDocuments, sendDocuments, deliveryPreview,
    setSelectedFiles, setVerification, setProgress, setProgressDetail, setStagingManifest,
    setSelectionError, isAbortUploadDialogOpen, setIsAbortUploadDialogOpen, setPhase, isSendPreviewOpen,
    setIsSendPreviewOpen, setDeliveryDocumentIds, setDeliveryResendDocumentIds, setDeliveryMessageContent1, setDeliveryMessageContent2,
    deliveryFeedback, setDeliveryFeedback, manualUploadTarget, setManualUploadTarget, processingUploadIds,
    hasIncompleteUploads, pendingRemovalDocumentIdSet, pendingRemovalPassengerCount, removalPending, defaultDeliveryDocumentIds,
    deliverySelection, activeDeliveryDocumentIds, activeDeliveryMessageContent1, activeDeliveryMessageContent2, pendingRemovalDocumentIds,
    setPendingRemovalDocumentIds, setSelectedDocumentIds, replaceManualReviewCandidates, forgetManualUpload,
    sendDelivery,
  } = controller;
  return <>
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
              onSuccess: (results) => {
                clearDocumentUploadRecovery(groupId, documentType);
                forgetManualUpload();
                setSelectedFiles([]);
                replaceManualReviewCandidates([]);
                setVerification(null);
                setStagingManifest(null);
                setSelectionError(null);
                setProgressDetail(null);
                setProgress(0);
                setPhase("idle");
                setIsAbortUploadDialogOpen(false);
                if (results.some((result) => result.status === "partial_retained")) {
                  setDeliveryFeedback("The unfinished upload was closed. Successfully uploaded replacements were kept and are ready for review and Save List.");
                }
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

      {manualUploadTarget && <ManualPassengerDocumentDialog key={`${manualUploadTarget.row.passenger_id}:${manualUploadTarget.mode}`} row={manualUploadTarget.row} mode={manualUploadTarget.mode} pending={manualUpload.isPending} error={manualUpload.error?.message ?? null} onClose={() => { if (!manualUpload.isPending) setManualUploadTarget(null); }} onUpload={(file, replacements) => manualUpload.mutate({ passengerId: manualUploadTarget.row.passenger_id, file, mode: manualUploadTarget.mode, replacements }, { onSuccess: () => setManualUploadTarget(null) })} />}

      {isSendPreviewOpen && (
        <DocumentDeliveryPreviewDialog
          preview={deliveryPreview.data}
          loading={deliveryPreview.isLoading}
          refreshing={deliveryPreview.isFetching}
          loadError={deliveryPreview.error}
          selectedDocumentIds={activeDeliveryDocumentIds}
          resendDocumentIds={deliverySelection.resendDocumentIds}
          sending={sendDocuments.isPending}
          sendError={sendDocuments.error}
          messageContent1={activeDeliveryMessageContent1}
          messageContent2={activeDeliveryMessageContent2}
          onMessageContent1Change={setDeliveryMessageContent1}
          onMessageContent2Change={setDeliveryMessageContent2}
          onRefresh={() => void deliveryPreview.refetch()}
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
          onSend={sendDelivery}
        />
      )}
  </>;
}
