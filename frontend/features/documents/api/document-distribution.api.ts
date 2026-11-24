import { documentReviewApi } from "./document-review.api";
import { documentVerificationApi } from "./document-verification.api";
import { documentBatchesApi } from "./document-batches.api";
import { documentDeliveryApi } from "./document-delivery.api";

/** Stable distribution facade; focused owners retain transport and receipt contracts. */
export const documentDistributionApi = {
  ...documentReviewApi,
  ...documentVerificationApi,
  ...documentBatchesApi,
  ...documentDeliveryApi,
};

export type { DocumentVerificationUploadPlan, DocumentAssignmentExportFilter } from "./document-distribution.types";
