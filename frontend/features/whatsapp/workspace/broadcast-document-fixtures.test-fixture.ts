import type { DocumentBatchReview, DistributedDocument } from "@/types/document-distribution.types";

const document: DistributedDocument = {
  id: "synthetic-document", original_filename: "synthetic.pdf", document_type: "visa",
  detected_type: "visa", match_status: "matched", match_confidence: 1,
  match_reason: null, extracted_name: null, extracted_passport_number: null,
  extracted_reference: null, source: "manual", delivery_status: "not_sent",
  sent_to: null, last_sent_at: null, can_resend: false, url: null,
};

export const syntheticBroadcastLinks = [{ group_id: "trip", passenger_id: "person" }];

export const syntheticBroadcastReview: DocumentBatchReview = {
  batch_id: "batch", group_id: "trip", document_type: "visa", status: "saved",
  uploaded_count: 1, rejected_count: 0, matched_count: 1, physical_file_count: 1,
  assigned_file_count: 1, assigned_passenger_count: 1, needs_assignment_count: 0,
  processing_upload_ids: [], saved_at: null, created_at: null,
  review_rows: [{ passenger_id: "person", passenger_name: "Synthetic passenger",
    passport_number: "SYNTHETIC", departure_city: null, document,
    documents: [document] }],
  unmatched_documents: [], assignment_issues: [], rejected_documents: [],
};
