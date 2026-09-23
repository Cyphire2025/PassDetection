export type EcrResult = "ECR" | "NA" | "NEEDS_REVIEW";
export type EcrBatchStatus = "uploading" | "queued" | "processing" | "completed" | "completed_with_errors";

export interface EcrItem {
  id: string;
  client_id: string;
  original_filename: string;
  status: "queued" | "processing" | "completed" | "failed";
  result: EcrResult | null;
  reason: string | null;
}

export interface EcrBatchSummary {
  batch_id: string;
  title: string;
  status: EcrBatchStatus;
  total_count: number;
  expected_count: number;
  processed_count: number;
  ecr_count: number;
  na_count: number;
  review_count: number;
  failed_count: number;
  created_at: string;
}

export interface EcrBatch extends EcrBatchSummary {
  items: EcrItem[];
}
