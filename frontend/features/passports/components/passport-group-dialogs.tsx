"use client";
import { ConfirmDialog } from "@/components/ui";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { tripDetailsUpdate } from "../utils/passport-group-update";
import {
  PassportExportDialog,
  PassportImageCropEditor,
  TripDetailsDialog,
} from "./passport-group-bindings";
import {
  createExportRequestId,
  mutationErrorMessage,
} from "./passport-group-model";
import type { PassportGroupController } from "./use-passport-group-controller";
export function PassportGroupDialogs({
  isEditingTrip,
  groupDetails,
  tripForm,
  updateGroup,
  setTripForm,
  setIsEditingTrip,
  groupId,
  imageEditor,
  canEditImages,
  setImageEditor,
  setImageRevisions,
  refetchSubmissions,
  exportDialogKind,
  exportImagesMutation,
  exportMutation,
  setExportDialogKind,
  setImportMessage,
  isBulkApprovalConfirmationOpen,
  selectedPassports,
  bulkStaffApprove,
  setIsBulkApprovalConfirmationOpen,
  selectedPassportRevisions,
  setBulkDeleteFeedback,
  setSelectedPassports,
  setSelectedPassportRevisions,
  setSelectionPreset,
  isBulkDeleteConfirmationOpen,
  bulkDelete,
  setIsBulkDeleteConfirmationOpen,
}: Pick<
  PassportGroupController,
  | "isEditingTrip"
  | "groupDetails"
  | "tripForm"
  | "updateGroup"
  | "setTripForm"
  | "setIsEditingTrip"
  | "groupId"
  | "imageEditor"
  | "canEditImages"
  | "setImageEditor"
  | "setImageRevisions"
  | "refetchSubmissions"
  | "exportDialogKind"
  | "exportImagesMutation"
  | "exportMutation"
  | "setExportDialogKind"
  | "setImportMessage"
  | "isBulkApprovalConfirmationOpen"
  | "selectedPassports"
  | "bulkStaffApprove"
  | "setIsBulkApprovalConfirmationOpen"
  | "selectedPassportRevisions"
  | "setBulkDeleteFeedback"
  | "setSelectedPassports"
  | "setSelectedPassportRevisions"
  | "setSelectionPreset"
  | "isBulkDeleteConfirmationOpen"
  | "bulkDelete"
  | "setIsBulkDeleteConfirmationOpen"
>) {
  return (
    <>
      {isEditingTrip && groupDetails && (
        <TripDetailsDialog
          form={tripForm}
          isLoading={updateGroup.isPending}
          saveError={updateGroup.isError ? mutationErrorMessage(updateGroup.error, "Trip details could not be saved. Please retry.") : undefined}
          onChange={setTripForm}
          onClose={() => { updateGroup.reset(); setIsEditingTrip(false); }}
          onSave={() => {
            updateGroup.mutate(
              tripDetailsUpdate(groupId, tripForm, groupDetails.group_name),
              { onSuccess: () => { updateGroup.reset(); setIsEditingTrip(false); } },
            );
          }}
        />
      )}
      {imageEditor && canEditImages && (
        <PassportImageCropEditor
          submissionId={imageEditor.submissionId}
          imageType={imageEditor.imageType}
          label={imageEditor.label}
          returnFocusTarget={imageEditor.returnFocusTarget}
          onClose={() => setImageEditor(null)}
          onSaved={() => {
            const { submissionId, imageType } = imageEditor;
            setImageRevisions((current) => ({
              ...current,
              [submissionId]: {
                ...current[submissionId],
                [imageType]: (current[submissionId]?.[imageType] ?? 0) + 1,
              },
            }));
            void refetchSubmissions();
          }}
        />
      )}
      {exportDialogKind && (
        <PassportExportDialog
          groupId={groupId}
          kind={exportDialogKind}
          isDownloading={
            exportDialogKind === "passport_images"
              ? exportImagesMutation.isPending
              : exportMutation.isPending
          }
          onClose={() => setExportDialogKind(null)}
          onDownload={async ({
            mode,
            baselineExportId,
            supplementalFields,
            groupByField,
            agencyMatchField,
          }) => {
            const mutation =
              exportDialogKind === "passport_images"
                ? exportImagesMutation
                : exportMutation;
            try {
              await mutation.mutateAsync({
                groupId,
                groupName: groupDetails?.group_name,
                mode,
                baselineExportId,
                supplementalFields,
                groupByField,
                agencyMatchField,
                requestId: createExportRequestId(),
              });
              setExportDialogKind(null);
            } catch (exportError) {
              if (isDownloadCancelled(exportError)) return;
              setExportDialogKind(null);
              setImportMessage(
                mutationErrorMessage(
                  exportError,
                  exportDialogKind === "passport_images"
                    ? "Image download failed"
                    : "Excel export failed",
                ),
              );
            }
          }}
        />
      )}
      <ConfirmDialog
        isOpen={isBulkApprovalConfirmationOpen}
        title="Staff approve selected submissions?"
        description={`Mark eligible records, including Client Submitted records, among ${selectedPassports.length} selected submission${selectedPassports.length === 1 ? "" : "s"} as Staff Approved? Processing, failed, and incomplete records will be left unchanged and reported.`}
        confirmLabel={`Approve ${selectedPassports.length} selected`}
        isLoading={bulkStaffApprove.isPending}
        onClose={() => {
          if (!bulkStaffApprove.isPending) {
            setIsBulkApprovalConfirmationOpen(false);
          }
        }}
        onConfirm={() => {
          if (selectedPassports.length === 0 || bulkStaffApprove.isPending)
            return;
          const approvalSelections = selectedPassports.flatMap(
            (submissionId) => {
              const expectedRevision = selectedPassportRevisions[submissionId];
              return expectedRevision === undefined
                ? []
                : [
                    {
                      submission_id: submissionId,
                      expected_extraction_revision: expectedRevision,
                    },
                  ];
            },
          );
          if (approvalSelections.length !== selectedPassports.length) {
            setIsBulkApprovalConfirmationOpen(false);
            setBulkDeleteFeedback({
              tone: "error",
              message:
                "The selection snapshot is incomplete. Refresh the group and select the submissions again.",
            });
            void refetchSubmissions();
            return;
          }
          bulkStaffApprove.mutate(approvalSelections, {
            onSuccess: (result) => {
              const retryableSkippedIds = result.skipped_submissions
                .filter((item) => item.reason === "not_completed")
                .map((item) => item.submission_id);
              const retryableSkippedIdSet = new Set(retryableSkippedIds);
              const staleCount = result.skipped_submissions.filter(
                (item) => item.reason === "stale",
              ).length;
              const incompleteCount = result.skipped_count - staleCount;
              setSelectedPassports(retryableSkippedIds);
              setSelectedPassportRevisions((revisions) =>
                Object.fromEntries(
                  Object.entries(revisions).filter(([submissionId]) =>
                    retryableSkippedIdSet.has(submissionId),
                  ),
                ),
              );
              setSelectionPreset("");
              setIsBulkApprovalConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: result.skipped_count > 0 ? "warning" : "success",
                message: [
                  `Staff approved ${result.approved_count} submission${result.approved_count === 1 ? "" : "s"}.`,
                  result.already_approved_count > 0
                    ? `${result.already_approved_count} were already Staff Approved.`
                    : "",
                  staleCount > 0
                    ? `${staleCount} submission${staleCount === 1 ? " changed" : "s changed"} after selection and must be refreshed and reviewed again.`
                    : "",
                  incompleteCount > 0
                    ? `${incompleteCount} incomplete or in-progress submission${incompleteCount === 1 ? " was" : "s were"} left unchanged.`
                    : "",
                  incompleteCount > 0
                    ? "Incomplete submissions remain selected."
                    : "",
                ]
                  .filter(Boolean)
                  .join(" "),
              });
              if (staleCount > 0) void refetchSubmissions();
            },
            onError: (approvalError) => {
              setIsBulkApprovalConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: "error",
                message: mutationErrorMessage(
                  approvalError,
                  "The selected passport submissions could not be staff approved.",
                ),
              });
            },
          });
        }}
      />
      <ConfirmDialog
        isOpen={isBulkDeleteConfirmationOpen}
        title="Delete selected submissions?"
        description={`Permanently delete ${selectedPassports.length} selected passport submission${selectedPassports.length === 1 ? "" : "s"}, including uploaded passport and Visa Photo files? This cannot be undone.`}
        confirmLabel={`Delete ${selectedPassports.length} submission${selectedPassports.length === 1 ? "" : "s"}`}
        variant="danger"
        isLoading={bulkDelete.isPending}
        onClose={() => {
          if (!bulkDelete.isPending) setIsBulkDeleteConfirmationOpen(false);
        }}
        onConfirm={() => {
          if (selectedPassports.length === 0 || bulkDelete.isPending) return;
          bulkDelete.mutate(selectedPassports, {
            onSuccess: (result) => {
              setSelectedPassports([]);
              setSelectedPassportRevisions({});
              setSelectionPreset("");
              setIsBulkDeleteConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: result.storage_cleanup_deferred ? "warning" : "success",
                message: result.storage_cleanup_deferred
                  ? `Deleted ${result.deleted_count} passport submission${result.deleted_count === 1 ? "" : "s"}. Stored-file cleanup could not finish and was logged for administrator follow-up.`
                  : `Deleted ${result.deleted_count} passport submission${result.deleted_count === 1 ? "" : "s"} and ${result.deleted_storage_objects} stored file${result.deleted_storage_objects === 1 ? "" : "s"}.`,
              });
            },
            onError: (deleteError) => {
              setIsBulkDeleteConfirmationOpen(false);
              setBulkDeleteFeedback({
                tone: "error",
                message: mutationErrorMessage(
                  deleteError,
                  "The selected passport submissions could not be deleted.",
                ),
              });
            },
          });
        }}
      />
    </>
  );
}
