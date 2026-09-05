"use client";

import { useRef } from "react";
import { SearchCheck, Trash2, UploadCloud } from "lucide-react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import type { DocumentDistributionLane } from "../config/document-distribution-lanes";

export type DocumentUploadPhase = "idle" | "checking" | "uploading";

export function DocumentUploadPanel({
  lane,
  passengerCount,
  selectedFileCount,
  acceptedFileCount,
  verificationReady,
  hasIncompleteUploads,
  canResumeCurrentUpload,
  processingUploadCount,
  uploadPending,
  verifyPending,
  abortPending,
  onFilesSelected,
  onCheck,
  onUpload,
  onDiscardIncomplete,
}: {
  lane: DocumentDistributionLane;
  passengerCount: number;
  selectedFileCount: number;
  acceptedFileCount: number;
  verificationReady: boolean;
  hasIncompleteUploads: boolean;
  canResumeCurrentUpload: boolean;
  processingUploadCount: number;
  uploadPending: boolean;
  verifyPending: boolean;
  abortPending: boolean;
  onFilesSelected: (files: File[]) => void;
  onCheck: () => void;
  onUpload: () => void;
  onDiscardIncomplete: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const operationPending = uploadPending || verifyPending;

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Upload {lane.title} PDFs
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Select all {lane.uploadLabel} files. The system checks document type and requires a confirmed in-group passenger match before upload.
              {lane.category === "flight_tickets" && (
                <> A combined Onward-and-Return PDF can be uploaded in both ticket sections.</>
              )}
            </p>
          </div>
          <Badge variant="outline">{passengerCount.toLocaleString()} {passengerCount === 1 ? "passenger" : "passengers"}</Badge>
        </div>

        {hasIncompleteUploads && (
          <div className="flex flex-col gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="font-semibold text-amber-950">
                {processingUploadCount === 1
                  ? "An incomplete upload needs attention"
                  : `${processingUploadCount} incomplete uploads need attention`}
              </div>
              <p className="mt-1 text-sm leading-5 text-amber-800">
                {canResumeCurrentUpload
                  ? "Continue the verified staged upload, or discard it before choosing new files."
                  : "Discard the incomplete upload data before choosing and uploading a new set of PDFs."}
              </p>
            </div>
            <Button
              type="button"
              variant="danger"
              disabled={operationPending || abortPending}
              onClick={onDiscardIncomplete}
            >
              <Trash2 className="h-4 w-4" />
              Discard incomplete {processingUploadCount === 1 ? "upload" : "uploads"}
            </Button>
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="hidden"
          onChange={(event) => {
            onFilesSelected(Array.from(event.target.files ?? []));
            event.currentTarget.value = "";
          }}
        />

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={() => inputRef.current?.click()}
            disabled={hasIncompleteUploads || operationPending}
          >
            <UploadCloud className="h-4 w-4" />
            Choose PDFs
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={onCheck}
            disabled={hasIncompleteUploads || selectedFileCount === 0 || operationPending}
          >
            <SearchCheck className="h-4 w-4" />
            Check Documents {selectedFileCount > 0 ? `(${selectedFileCount})` : ""}
          </Button>
          <Button
            type="button"
            onClick={onUpload}
            disabled={!verificationReady || acceptedFileCount === 0 || (hasIncompleteUploads && !canResumeCurrentUpload) || operationPending}
          >
            Upload Accepted {verificationReady ? `(${acceptedFileCount})` : ""}
          </Button>
          {selectedFileCount > 0 && (
            <span className="text-sm text-slate-500">
              {selectedFileCount} file{selectedFileCount === 1 ? "" : "s"} selected
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
