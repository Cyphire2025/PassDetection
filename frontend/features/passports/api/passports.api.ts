import { passportRecordsApi } from "./passport-records.api";
import { passportImagesApi } from "./passport-images.api";
import { passportVisaAiApi } from "./passport-visa-ai.api";
import { passportGroupExportsApi } from "./passport-group-exports.api";
import { passportImportsApi } from "./passport-imports.api";
import { passportSelectionExportsApi } from "./passport-selection-exports.api";

/** Stable dashboard facade; endpoint families retain their original transport contracts. */
export const passportsApi = {
  ...passportRecordsApi,
  ...passportImagesApi,
  ...passportVisaAiApi,
  ...passportGroupExportsApi,
  ...passportImportsApi,
  ...passportSelectionExportsApi,
};

export type {
  PassportGroupSubmissionFilter,
  PassportGroupSubmissionSort,
  PassportGroupSubmissionsViewParams,
  PassportExpiryAlert,
  PassportGroupSubmissionsView,
  BulkDeletePassportSubmissionsResult,
  PassportSubmissionSelectionSnapshot,
  BulkStaffApproveSkippedSubmission,
  BulkStaffApprovePassportSelection,
  BulkStaffApprovePassportSubmissionsResult,
  PassportReextractOutcome,
  PassportReextractResult,
} from "./passport-records.types";
export type {
  PassportImportResult,
  PassportDocumentImportItem,
  PassportDocumentImportPreview,
  PassportDocumentImportProgress,
  PassportDocumentImportRequest,
  PassportDocumentImportChunkRequest,
  PassportDocumentImportSaveResult,
} from "./passport-imports.types";
export type {
  PassportGroupExportKind,
  PassportGroupExportMode,
  PassportGroupExportHistoryItem,
  PassportGroupExportHistory,
  PassportGroupExportHistorySubmission,
  PassportGroupExportHistoryDetail,
  PassportGroupExportRequest,
  PassportWhatsAppTrackingStatus,
  PassportWhatsAppTrackingExportRequest,
  PassportGroupExportFieldOption,
  PassportGroupExportGroupingOption,
  PassportExcelFieldOptions,
  PassportGroupExportFieldOptions,
  PassportSelectedGroupsExportFieldOptions,
  PassportSelectedGroupsExportRequest,
  PassportSelectedImagesExportRequest,
  PassportGroupExportCompletion,
} from "./passport-exports.types";
export type {
  PassportImageCropRect,
  PassportImageCropState,
  SavePassportImageCropRequest,
  VisaAiEditPreview,
  ApplyVisaAiEditRequest,
  PassportImageLibrarySource,
  PassportImageLibraryItem,
  PassportImageLibrary,
  VisaAiLibraryImage,
  VisaAiLibrary,
  VisaAiGenerationJobStatus,
  VisaAiGenerationJob,
} from "./passport-images.types";
export type { PassportImageType } from "@/types/passport.types";
