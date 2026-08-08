import {
  CheckCircle2,
  FileQuestion,
  Save,
  Search,
  Send,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui";
import type { DocumentAssignmentIssue } from "@/types/document-distribution.types";
import type {
  DocumentReviewCounts,
  ReviewFilter,
} from "./document-workspace-model";

interface DocumentWorkspaceReviewControlsProps {
  assignedFileCount: number;
  assignedPassengerCount: number;
  needsAssignmentCount: number;
  rejectedCount: number;
  removalDocumentCount: number;
  removalPassengerCount: number;
  selectedAssignedDocumentCount: number;
  selectedUnmatchedDocumentCount: number;
  removalPending: boolean;
  removalConfirmationPending: boolean;
  deleteUnassignedPending: boolean;
  saveDisabled: boolean;
  savePending: boolean;
  saved: boolean;
  deliveryDisabled: boolean;
  hasReviewData: boolean;
  physicalFileCount: number;
  assignmentIssues: DocumentAssignmentIssue[];
  selectedDocumentIdSet: ReadonlySet<string>;
  reviewCounts: DocumentReviewCounts;
  reviewFilter: ReviewFilter;
  searchQuery: string;
  onRequestRemoval: () => void;
  onDeleteUnassigned: () => void;
  onSave: () => void;
  onOpenDelivery: () => void;
  onToggleIssue: (documentId: string, selected: boolean) => void;
  onReviewFilterChange: (filter: ReviewFilter) => void;
  onClearSelectedAssignments: () => void;
  onSearchQueryChange: (query: string) => void;
}

export function DocumentWorkspaceReviewControls({
  assignedFileCount,
  assignedPassengerCount,
  needsAssignmentCount,
  rejectedCount,
  removalDocumentCount,
  removalPassengerCount,
  selectedAssignedDocumentCount,
  selectedUnmatchedDocumentCount,
  removalPending,
  removalConfirmationPending,
  deleteUnassignedPending,
  saveDisabled,
  savePending,
  saved,
  deliveryDisabled,
  hasReviewData,
  physicalFileCount,
  assignmentIssues,
  selectedDocumentIdSet,
  reviewCounts,
  reviewFilter,
  searchQuery,
  onRequestRemoval,
  onDeleteUnassigned,
  onSave,
  onOpenDelivery,
  onToggleIssue,
  onReviewFilterChange,
  onClearSelectedAssignments,
  onSearchQueryChange,
}: DocumentWorkspaceReviewControlsProps) {
  return (
    <>
      <div className="flex flex-col gap-3 border-b border-slate-100 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Review Matches</h2>
          <p className="mt-1 text-sm text-slate-500">
            {assignedFileCount} files assigned across {assignedPassengerCount} passengers, {needsAssignmentCount} need assignment, {rejectedCount} rejected.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="danger"
            disabled={removalDocumentCount === 0 || removalPending}
            isLoading={removalConfirmationPending}
            onClick={onRequestRemoval}
          >
            <Trash2 className="h-4 w-4" />
            {selectedAssignedDocumentCount > 0
              ? `Remove assignments (${removalPassengerCount})`
              : `Remove all assigned (${removalPassengerCount})`}
          </Button>
          {selectedUnmatchedDocumentCount > 0 && (
            <Button
              type="button"
              variant="outline"
              disabled={removalPending}
              isLoading={deleteUnassignedPending}
              onClick={onDeleteUnassigned}
            >
              <Trash2 className="h-4 w-4" />
              Delete unassigned files ({selectedUnmatchedDocumentCount})
            </Button>
          )}
          <Button
            type="button"
            disabled={saveDisabled}
            isLoading={savePending}
            onClick={onSave}
          >
            <Save className="h-4 w-4" />
            {saved ? "Saved" : "Save List"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={deliveryDisabled}
            onClick={onOpenDelivery}
          >
            <Send className="h-4 w-4" />
            Send WhatsApp Broadcast
          </Button>
        </div>
      </div>

      {hasReviewData && physicalFileCount > 0 && (
        <div className={`border-b p-5 ${needsAssignmentCount > 0 ? "border-amber-200 bg-amber-50/70" : "border-emerald-100 bg-emerald-50/60"}`}>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className={`flex items-center gap-2 text-sm font-semibold ${needsAssignmentCount > 0 ? "text-amber-950" : "text-emerald-900"}`}>
                {needsAssignmentCount > 0 ? <FileQuestion className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                Needs assignment ({needsAssignmentCount})
              </h3>
              <p className={`mt-1 text-sm ${needsAssignmentCount > 0 ? "text-amber-800" : "text-emerald-800"}`}>
                {assignedFileCount} verified files are assigned across {assignedPassengerCount} passengers.
                {assignedFileCount !== assignedPassengerCount
                  ? " Multiple files can be correctly assigned to the same passenger."
                  : ""}
              </p>
            </div>
            <div className="text-xs font-medium text-slate-600">
              {physicalFileCount} verified files stored
            </div>
          </div>

          {assignmentIssues.length > 0 ? (
            <div className="mt-3 max-h-64 space-y-2 overflow-auto">
              {assignmentIssues.map((issue) => (
                <div key={issue.document_id} className="flex items-start gap-3 rounded-lg border border-amber-200 bg-white px-3 py-2.5 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-amber-300"
                    aria-label={`Select ${issue.original_filename}`}
                    checked={selectedDocumentIdSet.has(issue.document_id)}
                    disabled={removalPending}
                    onChange={(event) =>
                      onToggleIssue(issue.document_id, event.target.checked)
                    }
                  />
                  <div className="min-w-0 flex-1">
                    {issue.url ? (
                      <a href={issue.url} target="_blank" rel="noreferrer" className="break-all font-semibold text-amber-950 hover:underline">
                        {issue.original_filename}
                      </a>
                    ) : (
                      <div className="break-all font-semibold text-amber-950">{issue.original_filename}</div>
                    )}
                    <div className="mt-1 text-amber-800">{issue.reason}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-3 rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm text-emerald-800">
              Every verified stored file has a passenger assignment.
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        {([
          ["all", "All", reviewCounts.all],
          ["assigned", "Assigned", reviewCounts.assigned],
          ["missing", "Missing", reviewCounts.missing],
          ["sent", "Sent", reviewCounts.sent],
          ["not_sent", "Not sent", reviewCounts.not_sent],
        ] as Array<[ReviewFilter, string, number]>).map(([value, label, count]) => (
          <button
            key={value}
            type="button"
            onClick={() => onReviewFilterChange(value)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
              reviewFilter === value
                ? "border-blue-600 bg-blue-600 text-white"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
            }`}
          >
            {label} ({count})
          </button>
        ))}
        <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-3 sm:w-auto">
          {selectedAssignedDocumentCount > 0 && (
            <button
              type="button"
              className="text-xs font-medium text-blue-700 hover:underline"
              onClick={onClearSelectedAssignments}
            >
              Clear selected assignments
            </button>
          )}
          <label className="relative w-full sm:w-64">
            <span className="sr-only">Search passenger name</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
              placeholder="Search passenger name"
              className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
            />
          </label>
        </div>
      </div>
    </>
  );
}
