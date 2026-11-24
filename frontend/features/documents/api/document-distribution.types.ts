import type { DocumentVerificationResult } from "@/types/document-distribution.types";
import type { DocumentStagingManifest } from "../services/document-upload-batching";
import type { DocumentManualReviewCandidate } from "../services/document-manual-review";

export interface DocumentVerificationUploadPlan {
  verification: DocumentVerificationResult;
  stagingManifest: DocumentStagingManifest;
  manualReviewCandidates?: DocumentManualReviewCandidate[];
}

export type DocumentAssignmentExportFilter =
  | "all"
  | "assigned"
  | "missing"
  | "sent"
  | "not_sent"
  | "multiple_pdfs"
  | "shared_pdf";
