import type {
  DistributedDocument,
  DocumentAssignmentIssue,
  DocumentBatchReview,
  DocumentDeliveryPreview,
  DocumentPassengerReviewRow,
  DocumentVerificationResult,
} from "@/types/document-distribution.types";

export type ReviewFilter = "all" | "assigned" | "missing" | "sent" | "not_sent";

export interface DocumentReviewCounts {
  all: number;
  assigned: number;
  missing: number;
  sent: number;
  not_sent: number;
}

export interface DocumentReviewModel {
  rows: DocumentPassengerReviewRow[];
  documentsByPassengerId: ReadonlyMap<string, DistributedDocument[]>;
  counts: DocumentReviewCounts;
  assignmentIssues: DocumentAssignmentIssue[];
  assignedDocumentIds: string[];
  assignedDocumentIdSet: ReadonlySet<string>;
  assignedPassengerIds: ReadonlySet<string>;
  sentPassengerIds: ReadonlySet<string>;
  notSentPassengerIds: ReadonlySet<string>;
  unmatchedDocumentIds: string[];
  unmatchedDocumentIdSet: ReadonlySet<string>;
  selectableDocumentIdSet: ReadonlySet<string>;
}

export interface ActiveDocumentSelection {
  documentIds: string[];
  documentIdSet: ReadonlySet<string>;
  assignedDocumentIds: string[];
  assignedDocumentIdSet: ReadonlySet<string>;
  unmatchedDocumentIds: string[];
  unmatchedDocumentIdSet: ReadonlySet<string>;
}

const EMPTY_REVIEW_MODEL: DocumentReviewModel = {
  rows: [],
  documentsByPassengerId: new Map(),
  counts: { all: 0, assigned: 0, missing: 0, sent: 0, not_sent: 0 },
  assignmentIssues: [],
  assignedDocumentIds: [],
  assignedDocumentIdSet: new Set(),
  assignedPassengerIds: new Set(),
  sentPassengerIds: new Set(),
  notSentPassengerIds: new Set(),
  unmatchedDocumentIds: [],
  unmatchedDocumentIdSet: new Set(),
  selectableDocumentIdSet: new Set(),
};

const SENT_DOCUMENT_STATUSES = new Set(["submitted", "sent", "delivered", "read"]);

export function reviewRowDocuments(
  row: DocumentPassengerReviewRow,
): DistributedDocument[] {
  if (row.documents?.length) return row.documents;
  return row.document ? [row.document] : [];
}

export function createDocumentReviewModel(
  review: DocumentBatchReview | undefined,
): DocumentReviewModel {
  if (!review) return EMPTY_REVIEW_MODEL;

  const documentsByPassengerId = new Map<string, DistributedDocument[]>();
  const assignedDocumentIds: string[] = [];
  const assignedPassengerIds = new Set<string>();
  const sentPassengerIds = new Set<string>();
  const notSentPassengerIds = new Set<string>();

  for (const row of review.review_rows) {
    const documents = reviewRowDocuments(row);
    documentsByPassengerId.set(row.passenger_id, documents);
    if (documents.length === 0) continue;

    assignedPassengerIds.add(row.passenger_id);
    let hasSentDocument = false;
    let hasNotSentDocument = false;
    for (const document of documents) {
      assignedDocumentIds.push(document.id);
      if (SENT_DOCUMENT_STATUSES.has(document.delivery_status)) {
        hasSentDocument = true;
      } else {
        hasNotSentDocument = true;
      }
    }
    if (hasSentDocument) sentPassengerIds.add(row.passenger_id);
    if (hasNotSentDocument) notSentPassengerIds.add(row.passenger_id);
  }

  const unmatchedDocuments = review.unmatched_documents ?? [];
  const unmatchedDocumentIds = unmatchedDocuments.map((document) => document.id);
  const assignedDocumentIdSet = new Set(assignedDocumentIds);
  const unmatchedDocumentIdSet = new Set(unmatchedDocumentIds);
  const selectableDocumentIdSet = new Set([
    ...assignedDocumentIds,
    ...unmatchedDocumentIds,
  ]);
  const assignmentIssues = Array.isArray(review.assignment_issues)
    ? review.assignment_issues
    : unmatchedDocuments.map((document) => ({
        document_id: document.id,
        original_filename: document.original_filename,
        code: "no_unique_passenger_match",
        reason: document.match_reason || "No unique passenger match was found.",
        url: document.url,
      }));

  return {
    rows: review.review_rows,
    documentsByPassengerId,
    counts: {
      all: review.review_rows.length,
      assigned: assignedPassengerIds.size,
      missing: review.review_rows.length - assignedPassengerIds.size,
      sent: sentPassengerIds.size,
      not_sent: notSentPassengerIds.size,
    },
    assignmentIssues,
    assignedDocumentIds,
    assignedDocumentIdSet,
    assignedPassengerIds,
    sentPassengerIds,
    notSentPassengerIds,
    unmatchedDocumentIds,
    unmatchedDocumentIdSet,
    selectableDocumentIdSet,
  };
}

export function filterDocumentReviewRows(
  model: DocumentReviewModel,
  filter: ReviewFilter,
  searchQuery: string,
) {
  const normalizedSearch = searchQuery.trim().toLocaleLowerCase();
  return model.rows.filter((row) => {
    if (
      normalizedSearch
      && !row.passenger_name.toLocaleLowerCase().includes(normalizedSearch)
    ) {
      return false;
    }
    if (filter === "assigned") return model.assignedPassengerIds.has(row.passenger_id);
    if (filter === "missing") return !model.assignedPassengerIds.has(row.passenger_id);
    if (filter === "sent") return model.sentPassengerIds.has(row.passenger_id);
    if (filter === "not_sent") return model.notSentPassengerIds.has(row.passenger_id);
    return true;
  });
}

export function documentIdsForRows(
  rows: DocumentPassengerReviewRow[],
  documentsByPassengerId: ReadonlyMap<string, DistributedDocument[]>,
) {
  const documentIds: string[] = [];
  for (const row of rows) {
    for (const document of documentsByPassengerId.get(row.passenger_id) ?? []) {
      documentIds.push(document.id);
    }
  }
  return documentIds;
}

export function createActiveDocumentSelection(
  selectedDocumentIds: string[],
  model: DocumentReviewModel,
): ActiveDocumentSelection {
  const documentIds: string[] = [];
  const assignedDocumentIds: string[] = [];
  const unmatchedDocumentIds: string[] = [];
  for (const documentId of selectedDocumentIds) {
    if (!model.selectableDocumentIdSet.has(documentId)) continue;
    documentIds.push(documentId);
    if (model.assignedDocumentIdSet.has(documentId)) {
      assignedDocumentIds.push(documentId);
    }
    if (model.unmatchedDocumentIdSet.has(documentId)) {
      unmatchedDocumentIds.push(documentId);
    }
  }
  return {
    documentIds,
    documentIdSet: new Set(documentIds),
    assignedDocumentIds,
    assignedDocumentIdSet: new Set(assignedDocumentIds),
    unmatchedDocumentIds,
    unmatchedDocumentIdSet: new Set(unmatchedDocumentIds),
  };
}

export function countPassengersForDocuments(
  model: DocumentReviewModel,
  documentIds: ReadonlySet<string>,
) {
  let passengerCount = 0;
  for (const row of model.rows) {
    const documents = model.documentsByPassengerId.get(row.passenger_id) ?? [];
    if (documents.some((document) => documentIds.has(document.id))) {
      passengerCount += 1;
    }
  }
  return passengerCount;
}

export function updateSelectedDocumentIds(
  current: string[],
  documentIds: Iterable<string>,
  selected: boolean,
) {
  const targetIds = new Set(documentIds);
  const withoutTargets = current.filter((id) => !targetIds.has(id));
  return selected
    ? [...withoutTargets, ...Array.from(targetIds)]
    : withoutTargets;
}

export function acceptedStagingReceiptsFor(
  verification: DocumentVerificationResult | null,
) {
  if (!verification) return undefined;
  const receipts: Array<string | null> = [];
  for (const file of verification.files) {
    if (file.accepted) receipts.push(file.staging_receipt);
  }
  return receipts;
}

export function eligibleDeliveryDocumentIds(
  preview: DocumentDeliveryPreview | undefined,
) {
  if (!preview) return [];
  const documentIds: string[] = [];
  for (const recipient of preview.recipients) {
    if (recipient.eligible && recipient.document_id) {
      documentIds.push(recipient.document_id);
    }
  }
  return documentIds;
}
