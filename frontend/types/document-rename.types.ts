export interface RenameDocumentItem {
  id: string;
  original_filename: string;
  renamed_filename: string;
  detected_type: "visa" | "flight_ticket" | "unknown" | string;
  extracted_name: string | null;
  extracted_passport_number: string | null;
  extracted_reference: string | null;
  status: "renamed" | "needs_review" | "rejected" | string;
  reason: string | null;
  download_url: string;
}

export interface RenameDocumentBatch {
  batch_id: string;
  title: string;
  status: string;
  total_count: number;
  visa_count: number;
  ticket_count: number;
  unknown_count: number;
  zip_download_url: string;
  created_at: string;
  items: RenameDocumentItem[];
}

export interface RenameDocumentBatchSummary {
  batch_id: string;
  title: string;
  status: string;
  total_count: number;
  visa_count: number;
  ticket_count: number;
  unknown_count: number;
  zip_download_url: string;
  created_at: string;
}

export interface DeleteRenameBatchesResponse {
  deleted_count: number;
  deleted_storage_objects: number;
}
