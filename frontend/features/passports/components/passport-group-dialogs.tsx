"use client";
import { ConfirmDialog } from "@/components/ui";
import { normalizeCities } from "../utils/passport-group-trip";
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
  setImageRevision,
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
  | "setImageRevision"
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
          onChange={setTripForm}
          onClose={() => setIsEditingTrip(false)}
          onSave={() => {
            updateGroup.mutate(
              {
                id: groupId,
                name: tripForm.name.trim() || groupDetails.group_name,
                destination: tripForm.destination || null,
                travel_date: tripForm.travel_date || null,
                return_date: tripForm.return_date || null,
                timezone: tripForm.timezone.trim(),
                departure_cities: tripForm.nearest_international_airport_enabled
                  ? normalizeCities(tripForm.departure_cities)
                  : [],
                base_city_enabled: tripForm.base_city_enabled,
                nearest_international_airport_enabled:
                  tripForm.nearest_international_airport_enabled,
                staff_code_enabled: tripForm.staff_code_enabled,
                agent_employee_code_enabled:
                  tripForm.agent_employee_code_enabled,
                meal_preference_enabled: tripForm.meal_preference_enabled,
                upload_configuration: tripForm.upload_configuration,
                custom_questions: tripForm.custom_questions,
                custom_details: tripForm.custom_details,
                require_selfie: tripForm.require_selfie,
                allow_files_from_device: tripForm.allow_files_from_device,
                ask_nearest_domestic_airport:
                  tripForm.ask_nearest_domestic_airport,
                relation_with_qualifier_enabled:
                  tripForm.relation_with_qualifier_enabled,
                designation_enabled: tripForm.designation_enabled,
                agency_dealership_name_enabled:
                  tripForm.agency_dealership_name_enabled,
                notes: tripForm.notes || null,
              },
              { onSuccess: () => setIsEditingTrip(false) },
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
            setImageRevision((current) => current + 1);
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
          onDownload={({
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
            mutation.mutate(
              {
                groupId,
                groupName: groupDetails?.group_name,
                mode,
                baselineExportId,
                supplementalFields,
                groupByField,
                agencyMatchField,
                requestId: createExportRequestId(),
              },
              {
                onSuccess: () => setExportDialogKind(null),
                onError: (exportError) => {
                  setExportDialogKind(null);
                  setImportMessage(
                    mutationErrorMessage(
                      exportError,
                      exportDialogKind === "passport_images"
                        ? "Image download failed"
                        : "Excel export failed",
                    ),
                  );
                },
              },
            );
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
