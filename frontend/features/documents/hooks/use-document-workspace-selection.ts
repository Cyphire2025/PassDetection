"use client";
import { useMemo, useState } from "react";
import type { DocumentBatchReview, DistributionDocumentType } from "@/types/document-distribution.types";
import {
  createDocumentReviewModel, filterDocumentReviewRows, documentIdsForRows, createActiveDocumentSelection,
  countPassengersForDocuments, type ReviewFilter
} from "../components/document-workspace-model";

export function useDocumentWorkspaceSelection(review: { data: DocumentBatchReview | undefined }, documentType: DistributionDocumentType) {
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [reviewSearchQuery, setReviewSearchQuery] = useState("");
  const [pendingRemovalDocumentIds, setPendingRemovalDocumentIds] = useState<string[] | null>(null);
  const reviewModel = useMemo(
    () => createDocumentReviewModel(review.data),
    [review.data],
  );
  const reviewCounts = reviewModel.counts;
  const assignmentIssues = reviewModel.assignmentIssues;
  const assignedDocumentIds = reviewModel.assignedDocumentIds;
  const visibleReviewRows = useMemo(
    () => filterDocumentReviewRows(reviewModel, reviewFilter, reviewSearchQuery),
    [reviewFilter, reviewModel, reviewSearchQuery],
  );
  const visibleAssignedDocumentIds = useMemo(
    () => documentIdsForRows(
      visibleReviewRows,
      reviewModel.documentsByPassengerId,
    ),
    [reviewModel.documentsByPassengerId, visibleReviewRows],
  );
  const activeSelection = useMemo(
    () => createActiveDocumentSelection(selectedDocumentIds, reviewModel),
    [reviewModel, selectedDocumentIds],
  );
  const activeSelectedDocumentIdSet = activeSelection.documentIdSet;
  const activeSelectedAssignedDocumentIds = activeSelection.assignedDocumentIds;
  const activeSelectedAssignedDocumentIdSet = activeSelection.assignedDocumentIdSet;
  const activeSelectedUnmatchedDocumentIds = activeSelection.unmatchedDocumentIds;
  const activeSelectedUnmatchedDocumentIdSet = activeSelection.unmatchedDocumentIdSet;
  const selectedAssignedPassengerCount = useMemo(
    () => countPassengersForDocuments(
      reviewModel,
      activeSelection.assignedDocumentIdSet,
    ),
    [activeSelection.assignedDocumentIdSet, reviewModel],
  );
  const allVisibleAssignmentsSelected =
    visibleAssignedDocumentIds.length > 0
    && visibleAssignedDocumentIds.every((id) =>
      activeSelectedAssignedDocumentIdSet.has(id),
    );
  const removalDocumentIds =
    activeSelectedAssignedDocumentIds.length > 0
      ? activeSelectedAssignedDocumentIds
      : assignedDocumentIds;
  const removalPassengerCount =
    activeSelectedAssignedDocumentIds.length > 0
      ? selectedAssignedPassengerCount
      : reviewCounts.assigned;
  const pendingRemovalDocumentIdSet = useMemo(
    () => new Set(pendingRemovalDocumentIds ?? []),
    [pendingRemovalDocumentIds],
  );
  const pendingRemovalPassengerCount = useMemo(
    () => pendingRemovalDocumentIds
      ? countPassengersForDocuments(reviewModel, pendingRemovalDocumentIdSet)
      : 0,
    [pendingRemovalDocumentIdSet, pendingRemovalDocumentIds, reviewModel],
  );
  const physicalFileCount =
    review.data?.physical_file_count ?? review.data?.uploaded_count ?? 0;
  const assignedFileCount =
    review.data?.assigned_file_count
    ?? Math.max(physicalFileCount - assignmentIssues.length, 0);
  const assignedPassengerCount =
    review.data?.assigned_passenger_count ?? reviewCounts.assigned;
  const needsAssignmentCount =
    review.data?.needs_assignment_count ?? assignmentIssues.length;
  const showRowActions =
    documentType === "visa" || documentType.startsWith("flight_ticket");
  return {
    selectedDocumentIds, setSelectedDocumentIds, reviewFilter, setReviewFilter, reviewSearchQuery, setReviewSearchQuery,
    pendingRemovalDocumentIds, setPendingRemovalDocumentIds, reviewModel, reviewCounts, assignmentIssues, assignedDocumentIds,
    visibleReviewRows, visibleAssignedDocumentIds, activeSelectedDocumentIdSet, activeSelectedAssignedDocumentIds,
    activeSelectedAssignedDocumentIdSet, activeSelectedUnmatchedDocumentIds, activeSelectedUnmatchedDocumentIdSet,
    selectedAssignedPassengerCount, allVisibleAssignmentsSelected, removalDocumentIds, removalPassengerCount,
    pendingRemovalDocumentIdSet, pendingRemovalPassengerCount, physicalFileCount, assignedFileCount,
    assignedPassengerCount, needsAssignmentCount, showRowActions,
  };
}
