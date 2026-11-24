import { CheckCircle2, FileX2 } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { DocumentVerificationResult } from "@/types/document-distribution.types";

type VerificationPanelProps = {
  verification: DocumentVerificationResult;
  reviewableFileIndexes?: ReadonlySet<number>;
  selectedReviewFileIndexes?: ReadonlySet<number>;
  manualReviewDisabled?: boolean;
  manualReviewLocked?: boolean;
  onReviewFile?: (index: number) => void;
  onToggleReviewFile?: (index: number, selected: boolean) => void;
  onSelectAllReviewFiles?: (selected: boolean) => void;
  onReviewSelected?: () => void;
};

export function VerificationPanel({
  verification,
  reviewableFileIndexes,
  selectedReviewFileIndexes,
  manualReviewDisabled = false,
  manualReviewLocked = false,
  onReviewFile,
  onToggleReviewFile,
  onSelectAllReviewFiles,
  onReviewSelected,
}: VerificationPanelProps) {
  const indexedFiles = verification.files.map((file, index) => ({ file, index }));
  const accepted = indexedFiles.filter(({ file }) => file.accepted && !file.uploaded && !file.manual_uploaded);
  const uploadedCount = indexedFiles.filter(({ file }) => file.uploaded || file.manual_uploaded).length;
  const manuallyUploadedCount = indexedFiles.filter(({ file }) => file.manual_uploaded).length;
  const rejected = indexedFiles.filter(({ file }) => !file.accepted);
  const hasManualReview = rejected.some(({ file }) => file.manual_review_available && !file.manual_type_approved);
  const eligibleReviewIndexes = new Set(rejected.flatMap(({ file, index }) =>
    file.detected_type === "unknown" && file.manual_review_available
      && !file.manual_type_approved && reviewableFileIndexes?.has(index)
      ? [index]
      : [],
  ));
  const selectedReviewCount = [...eligibleReviewIndexes].filter((index) => selectedReviewFileIndexes?.has(index)).length;
  const allReviewFilesSelected = eligibleReviewIndexes.size > 0 && selectedReviewCount === eligibleReviewIndexes.size;
  const someReviewFilesSelected = selectedReviewCount > 0 && !allReviewFilesSelected;
  const supportsReviewSelection = Boolean(onToggleReviewFile && onSelectAllReviewFiles && onReviewSelected);
  const reviewControlsDisabled = manualReviewDisabled || manualReviewLocked;

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50">
      <div className="flex flex-col gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Document Check Results</h3>
          <p className="mt-1 text-sm text-slate-500">
            {verification.accepted_count} accepted, {verification.rejected_count} rejected from {verification.total_count} selected {verification.total_count === 1 ? "file" : "files"}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="success">{verification.accepted_count} accepted</Badge>
          <Badge variant={verification.rejected_count > 0 ? "destructive" : "outline"}>{verification.rejected_count} rejected</Badge>
        </div>
      </div>

      {hasManualReview && (
        <p className="border-b border-slate-200 px-4 py-3 text-sm text-slate-600">
          {manualReviewLocked
            ? "An upload is incomplete. Finish or discard it before approving and uploading more PDFs."
            : supportsReviewSelection
              ? "Select PDFs whose type could not be identified, then approve and upload your selection. A confirmed passenger match is still required. After a page refresh, select and check the original PDFs again to review them."
              : "If the document type could not be identified, review the PDF and approve its type before clicking Upload Accepted. A confirmed passenger match is still required. After a page refresh, select and check the original PDFs again to review them."}
        </p>
      )}

      {uploadedCount > 0 && (
        <p role="status" className="flex items-center gap-2 border-b border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            {uploadedCount} {uploadedCount === 1 ? "PDF" : "PDFs"} uploaded
            {manuallyUploadedCount > 0 ? ` · ${manuallyUploadedCount} manually approved` : ""}.
          </span>
        </p>
      )}

      <div className="grid gap-4 p-4 lg:grid-cols-2">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-green-800">
            <CheckCircle2 className="h-4 w-4" />
            Ready To Upload
            <span className="text-xs tabular-nums">({accepted.length})</span>
          </div>
          <div className="max-h-72 overflow-auto rounded-lg border border-green-100 bg-white">
            {accepted.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">
                {uploadedCount > 0 ? "No accepted PDFs are waiting to be uploaded." : "No files passed the document check."}
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {accepted.map(({ file, index }) => (
                  <div key={index} className="p-3 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-slate-900">{file.filename}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          <VerificationMatchText file={file} />
                        </div>
                      </div>
                      <Badge variant="success">{file.manual_type_approved ? "Manually approved" : file.detected_type}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-800">
            <FileX2 className="h-4 w-4" />
            Rejected Files
          </div>
          {hasManualReview && supportsReviewSelection && (
            <div className="mb-2 space-y-2 rounded-lg border border-slate-200 bg-white p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
                  <input
                    ref={(element) => { if (element) element.indeterminate = someReviewFilesSelected; }}
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300"
                    checked={allReviewFilesSelected}
                    aria-checked={someReviewFilesSelected ? "mixed" : allReviewFilesSelected}
                    disabled={reviewControlsDisabled || eligibleReviewIndexes.size === 0}
                    onChange={(event) => onSelectAllReviewFiles?.(event.target.checked)}
                  />
                  Select all eligible
                </label>
                <span className="text-xs tabular-nums text-slate-500" role="status">
                  {selectedReviewCount} of {eligibleReviewIndexes.size} selected
                </span>
              </div>
              <Button
                type="button"
                size="sm"
                className="h-auto min-h-8 w-full whitespace-normal"
                disabled={reviewControlsDisabled || selectedReviewCount === 0}
                onClick={onReviewSelected}
              >
                Approve &amp; upload selected ({selectedReviewCount})
              </Button>
            </div>
          )}
          <div className="max-h-72 overflow-auto rounded-lg border border-red-100 bg-white">
            {rejected.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No files were rejected.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {rejected.map(({ file, index }) => (
                  <div key={index} className="p-3 text-sm">
                    <div className="flex items-start gap-3">
                      {supportsReviewSelection && eligibleReviewIndexes.has(index) && (
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300"
                          aria-label={`Select file ${index + 1}: ${file.filename} for review`}
                          checked={selectedReviewFileIndexes?.has(index) ?? false}
                          disabled={reviewControlsDisabled}
                          onChange={(event) => onToggleReviewFile?.(index, event.target.checked)}
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium text-slate-900">{file.filename}</div>
                        <div className="mt-1 text-xs text-red-700">{file.reason}</div>
                        {file.manual_type_approved && (
                          <p className="mt-1 text-xs text-slate-600">Type approved; a confirmed passenger match is still needed before upload.</p>
                        )}
                      </div>
                      <Badge variant={file.manual_type_approved ? "outline" : "destructive"}>
                        {file.manual_type_approved ? "Type approved" : file.detected_type}
                      </Badge>
                    </div>
                    {file.manual_review_available && !file.manual_type_approved && (!supportsReviewSelection || !reviewableFileIndexes?.has(index)) && (
                      <div className="mt-2">
                        {onReviewFile && !supportsReviewSelection && (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={reviewControlsDisabled || !reviewableFileIndexes?.has(index)}
                            onClick={() => onReviewFile(index)}
                            aria-label={`Review and approve ${file.filename}`}
                          >
                            Review &amp; approve
                          </Button>
                        )}
                        {!reviewableFileIndexes?.has(index) && (
                          <p className="mt-1 text-xs text-slate-500">Select and check this PDF again to review its type.</p>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

type VerificationFile = DocumentVerificationResult["files"][number];

function VerificationMatchText({ file }: { file: VerificationFile }) {
  const names = file.matched_passenger_names ?? [];
  if (names.length > 1) {
    return (
      <>
        Matched {names.length} passengers: {names.slice(0, 4).join(", ")}
        {names.length > 4 ? `, +${names.length - 4} more` : ""}
      </>
    );
  }
  if (file.matched_passenger_name) return <>Matched {file.matched_passenger_name}</>;
  return <>{file.match_reason || "Accepted"}</>;
}
