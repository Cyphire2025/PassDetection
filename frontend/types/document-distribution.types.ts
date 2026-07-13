export type DistributionDocumentType = "visa" | "flight_ticket" | "other";

export interface DocumentDistributionGroup {
  group_id: string;
  group_name: string;
  group_status: string;
  destination: string | null;
  travel_date: string | null;
  total_passengers: number;
}

export interface RejectedDistributedDocument {
  filename: string;
  detected_type: string;
  reason: string;
}

export interface VerifiedDistributedDocument {
  filename: string;
  detected_type: string;
  accepted: boolean;
  reason: string;
  matched_passenger_id: string | null;
  matched_passenger_name: string | null;
  match_confidence: number;
  match_status: string | null;
  match_reason: string | null;
}

export interface DocumentVerificationResult {
  group_id: string;
  document_type: DistributionDocumentType | string;
  total_count: number;
  accepted_count: number;
  rejected_count: number;
  files: VerifiedDistributedDocument[];
}

export interface DistributedDocument {
  id: string;
  original_filename: string;
  document_type: DistributionDocumentType | string;
  detected_type: string;
  match_status: "matched" | "needs_review" | "duplicate_document" | string;
  match_confidence: number;
  match_reason: string | null;
  extracted_name: string | null;
  extracted_passport_number: string | null;
  extracted_reference: string | null;
  url: string | null;
}

export interface DocumentPassengerReviewRow {
  passenger_id: string;
  passenger_name: string;
  passport_number: string | null;
  departure_city: string | null;
  document: DistributedDocument | null;
}

export interface DocumentBatchReview {
  batch_id: string | null;
  group_id: string;
  document_type: DistributionDocumentType | string;
  status: string;
  uploaded_count: number;
  rejected_count: number;
  matched_count: number;
  saved_at: string | null;
  created_at: string | null;
  review_rows: DocumentPassengerReviewRow[];
  unmatched_documents: DistributedDocument[];
  rejected_documents: RejectedDistributedDocument[];
}
