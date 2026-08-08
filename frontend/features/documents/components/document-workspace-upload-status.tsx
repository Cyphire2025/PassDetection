import { Card, CardContent } from "@/components/ui";
import type { DocumentVerificationResult } from "@/types/document-distribution.types";
import type { DocumentUploadProgress } from "../services/document-upload-batching";
import type { DocumentUploadPhase } from "./document-upload-panel";
import { VerificationPanel } from "./document-workspace-review";

interface DocumentWorkspaceUploadStatusProps {
  phase: DocumentUploadPhase;
  progress: number;
  progressDetail: DocumentUploadProgress | null;
  uploadPending: boolean;
  uploadError: Error | null;
  selectionError: string | null;
  verifyError: Error | null;
  reuploadError: Error | null;
  deleteError: Error | null;
  unassignError: Error | null;
  verification: DocumentVerificationResult | null;
}

export function DocumentWorkspaceUploadStatus({
  phase,
  progress,
  progressDetail,
  uploadPending,
  uploadError,
  selectionError,
  verifyError,
  reuploadError,
  deleteError,
  unassignError,
  verification,
}: DocumentWorkspaceUploadStatusProps) {
  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        {(uploadPending || phase !== "idle") && (
          <div className="space-y-2 rounded-lg border border-blue-100 bg-blue-50 p-3">
            <div className="flex items-center justify-between text-sm font-medium text-blue-900">
              <span>
                {phase === "checking"
                  ? progressDetail?.phase === "processing"
                    ? "Checking PDFs in parallel"
                    : "Preparing parallel PDF checks"
                  : progressDetail?.phase === "processing"
                    ? "Matching and saving PDFs"
                    : "Uploading accepted PDFs"}
                {progressDetail
                  ? ` — ${progressDetail.completedFiles}/${progressDetail.totalFiles} complete`
                  : ""}
              </span>
              <span>{progress}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white">
              <div
                className="h-full rounded-full bg-blue-600 transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {uploadError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {uploadError.message}
            {progressDetail && progressDetail.completedFiles > 0
              ? ` ${progressDetail.completedFiles} of ${progressDetail.totalFiles} PDFs are safely committed; click Upload Accepted again to resume.`
              : ""}
          </div>
        )}

        {selectionError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {selectionError}
          </div>
        )}

        {verifyError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {verifyError.message}
          </div>
        )}

        {reuploadError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {reuploadError.message}
          </div>
        )}

        {deleteError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {deleteError.message}
          </div>
        )}

        {unassignError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {unassignError.message}
          </div>
        )}

        {verification && <VerificationPanel verification={verification} />}
      </CardContent>
    </Card>
  );
}
