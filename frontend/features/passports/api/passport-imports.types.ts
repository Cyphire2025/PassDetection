export interface PassportImportResult {
  imported_count: number;
  updated_count: number;
  skipped_count: number;
}

export interface PassportDocumentImportItem {
  filename: string;
  staff_code?: string | null;
  document_type?: "photo" | "front" | "back" | null;
  passenger_id?: string | null;
  passenger_name?: string | null;
  accepted: boolean;
  reason?: string | null;
}

export interface PassportDocumentImportPreview {
  group_id: string;
  total_count: number;
  accepted_count: number;
  rejected_count: number;
  accepted_documents: PassportDocumentImportItem[];
  rejected_documents: PassportDocumentImportItem[];
}

export interface PassportDocumentImportProgress {
  phase: "preparing" | "uploading" | "checking" | "saving";
  loaded: number;
  total: number;
}

export interface PassportDocumentImportRequest {
  files: File[];
  onProgress?: (progress: PassportDocumentImportProgress) => void;
}

export interface PassportDocumentImportChunkRequest extends PassportDocumentImportRequest {
  maxChunkBytes?: number;
  maxChunkFiles?: number;
}

export type PassportDocumentImportSaveResult = PassportDocumentImportPreview & { saved_count: number };
