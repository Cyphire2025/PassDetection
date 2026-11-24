import { Button, Input } from "@/components/ui";
import type { PassportGroupSubmissionFilter, PassportGroupSubmissionSort } from "../api/passports.api";
import { MAX_BULK_SELECTION } from "./passport-group-bindings";
import type { PassportGroupSelectionToolbarProps } from "./passport-group-selection-toolbar";

type Props = Pick<
  PassportGroupSelectionToolbarProps,
  | "sortBy"
  | "setSortBy"
  | "setPage"
  | "submissionFilter"
  | "setSubmissionFilter"
  | "submissionsView"
  | "sortOrder"
  | "setSortOrder"
  | "selectionPreset"
  | "handleSelectionPreset"
  | "customSelectionCount"
  | "setCustomSelectionCount"
  | "customSelectionIsValid"
  | "selectFirstPassports"
  | "parsedCustomSelectionCount"
>;

export function PassportGroupFilterControls({
  sortBy,
  setSortBy,
  setPage,
  submissionFilter,
  setSubmissionFilter,
  submissionsView,
  sortOrder,
  setSortOrder,
  selectionPreset,
  handleSelectionPreset,
  customSelectionCount,
  setCustomSelectionCount,
  customSelectionIsValid,
  selectFirstPassports,
  parsedCustomSelectionCount
}: Props) {
  return (<>
    <label className="sr-only" htmlFor="group-submission-sort">
      Sort submissions by
    </label>
    <select
      id="group-submission-sort"
      value={sortBy}
      onChange={(event) => {
        setSortBy(event.target.value as PassportGroupSubmissionSort);
        setPage(1);
      }}
      className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
    >
      <option value="name">Sort by: Name</option>
      <option value="updated_at">Sort by: Updated</option>
      <option value="verification_confidence">
        Sort by: Verification confidence
      </option>
    </select>
    <label className="sr-only" htmlFor="group-submission-filter">
      Filter submissions
    </label>
    <select
      id="group-submission-filter"
      value={submissionFilter}
      onChange={(event) => {
        setSubmissionFilter(
          event.target.value as PassportGroupSubmissionFilter,
        );
        setPage(1);
      }}
      className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
    >
      <option value="all">All submissions</option>
      <option value="pending_ai">Pending AI Verification</option>
      <option value="ai_approved">AI Approved</option>
      <option value="needs_review">Needs Review</option>
      <option value="staff_approved">Staff Approved</option>
      <option value="duplicates">Duplicates</option>
      {(submissionsView?.document_follow_up_count ?? 0) > 0 && (
        <option value="document_follow_up">Flagged for follow-up</option>
      )}
    </select>
    <label className="sr-only" htmlFor="group-submission-sort-order">
      Sort direction
    </label>
    <select
      id="group-submission-sort-order"
      value={sortOrder}
      onChange={(event) => {
        setSortOrder(event.target.value as "asc" | "desc");
        setPage(1);
      }}
      className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
    >
      <option value="asc">Ascending</option>
      <option value="desc">Descending</option>
    </select>
    <label className="sr-only" htmlFor="group-submission-selection">
      Select submissions
    </label>
    <select
      id="group-submission-selection"
      value={selectionPreset}
      disabled={(submissionsView?.total ?? 0) === 0}
      onChange={(event) => handleSelectionPreset(event.target.value)}
      className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <option value="">Select passengers</option>
      <option value="all">
        {(submissionsView?.total ?? 0) > MAX_BULK_SELECTION
          ? "First 1,500 (maximum)"
          : "All"}
      </option>
      <option value="50">First 50</option>
      <option value="100">First 100</option>
      <option value="200">First 200</option>
      <option value="custom">Custom number</option>
    </select>
    {selectionPreset === "custom" && (
      <div className="flex shrink-0 items-center gap-2">
        <label
          className="sr-only"
          htmlFor="group-submission-custom-selection"
        >
          Number of submissions to select
        </label>
        <Input
          id="group-submission-custom-selection"
          type="number"
          min={1}
          max={Math.min(
            MAX_BULK_SELECTION,
            Math.max(1, submissionsView?.total ?? 1),
          )}
          value={customSelectionCount}
          onChange={(event) => setCustomSelectionCount(event.target.value)}
          className="h-9 w-28"
          placeholder="Count"
        />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={!customSelectionIsValid}
          onClick={() => {
            if (customSelectionIsValid) {
              selectFirstPassports(parsedCustomSelectionCount);
            }
          }}
        >
          Apply
        </Button>
      </div>
    )}
  </>);
}
