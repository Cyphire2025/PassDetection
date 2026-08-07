import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  FileX2,
  MoreVertical,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui";
import type {
  DistributedDocument,
  DistributionDocumentType,
  DocumentPassengerReviewRow,
  DocumentVerificationResult,
} from "@/types/document-distribution.types";
import { distributionDocumentUploadLabel } from "../config/document-distribution-lanes";

type VerificationPanelProps = {
  verification: DocumentVerificationResult;
};

export function VerificationPanel({ verification }: VerificationPanelProps) {
  const accepted = verification.files.filter((file) => file.accepted);
  const rejected = verification.files.filter((file) => !file.accepted);

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50">
      <div className="flex flex-col gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Document Check Results</h3>
          <p className="mt-1 text-sm text-slate-500">
            {verification.accepted_count} accepted, {verification.rejected_count} rejected from {verification.total_count} selected files.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="success">{verification.accepted_count} accepted</Badge>
          <Badge variant={verification.rejected_count > 0 ? "destructive" : "outline"}>{verification.rejected_count} rejected</Badge>
        </div>
      </div>

      <div className="grid gap-4 p-4 lg:grid-cols-2">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-green-800">
            <CheckCircle2 className="h-4 w-4" />
            Ready To Upload
          </div>
          <div className="max-h-72 overflow-auto rounded-lg border border-green-100 bg-white">
            {accepted.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No files passed the document check.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {accepted.map((file) => (
                  <div key={file.filename} className="p-3 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-slate-900">{file.filename}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          <VerificationMatchText file={file} />
                        </div>
                      </div>
                      <Badge variant="success">{file.detected_type}</Badge>
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
          <div className="max-h-72 overflow-auto rounded-lg border border-red-100 bg-white">
            {rejected.length === 0 ? (
              <div className="p-4 text-sm text-slate-500">No files were rejected.</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {rejected.map((file) => (
                  <div key={file.filename} className="p-3 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-slate-900">{file.filename}</div>
                        <div className="mt-1 text-xs text-red-700">{file.reason}</div>
                      </div>
                      <Badge variant="destructive">{file.detected_type}</Badge>
                    </div>
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

type DocumentRowActionMenuProps = {
  row: DocumentPassengerReviewRow;
  documents: DistributedDocument[];
  documentType: DistributionDocumentType;
  pending: boolean;
  onReupload: (file: File) => void;
  onRemoveAssignment: (documentId: string) => void;
};

export function DocumentRowActionMenu({
  row,
  documents,
  documentType,
  pending,
  onReupload,
  onRemoveAssignment,
}: DocumentRowActionMenuProps) {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const label = distributionDocumentUploadLabel(documentType);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={menuRef} className="relative inline-flex justify-end">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.currentTarget.value = "";
          setOpen(false);
          if (file) onReupload(file);
        }}
      />
      <button
        type="button"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        aria-label={`${row.passenger_name} document actions`}
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={pending}
        onClick={() => setOpen((current) => !current)}
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-10 z-30 w-72 rounded-lg border border-slate-200 bg-white py-1 text-left shadow-lg">
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            onClick={() => inputRef.current?.click()}
          >
            <RefreshCw className="h-4 w-4" />
            Add another document
          </button>
          {documents.length > 0 && <div className="my-1 border-t border-slate-100" />}
          {documents.map((document) => (
            <button
              key={document.id}
              type="button"
              role="menuitem"
              className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
              onClick={() => {
                setOpen(false);
                onRemoveAssignment(document.id);
              }}
            >
              <FileX2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">Remove assignment</span>
                <span className="block truncate text-xs text-slate-500" title={document.original_filename}>
                  {document.original_filename}
                </span>
              </span>
            </button>
          ))}
          <div className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
            Upload one more {label} PDF without removing saved documents.
          </div>
        </div>
      )}
    </div>
  );
}

type DocumentSentStatusProps = {
  status: string;
  sentTo: string | null;
  sentAt: string | null;
  canResend: boolean;
  onResend: () => void;
};

export function DocumentSentStatus({
  status,
  sentTo,
  sentAt,
  canResend,
  onResend,
}: DocumentSentStatusProps) {
  if (status === "sent") {
    return (
      <div className="min-w-40">
        <Badge variant="success">Sent</Badge>
        <div className="mt-1 text-xs font-medium text-slate-700">
          {sentTo || "WhatsApp accepted"}
        </div>
        {sentAt && (
          <div className="mt-0.5 text-xs text-slate-500">
            {new Date(sentAt).toLocaleString()}
          </div>
        )}
        {canResend && (
          <button
            type="button"
            onClick={onResend}
            className="mt-2 text-xs font-semibold text-blue-700 hover:text-blue-800 hover:underline"
          >
            Resend explicitly
          </button>
        )}
      </div>
    );
  }
  if (status === "queued" || status === "processing") {
    return <Badge variant="outline">In progress</Badge>;
  }
  if (status === "delivery_unknown") {
    return <Badge variant="warning">Outcome unknown</Badge>;
  }
  if (status === "failed") {
    return <Badge variant="destructive">Failed</Badge>;
  }
  return <Badge variant="outline">Not sent</Badge>;
}

export function MatchBadge({ status }: { status: string }) {
  if (status === "matched") {
    return (
      <Badge variant="success" dot>
        <CheckCircle2 className="h-3 w-3" />
        Matched
      </Badge>
    );
  }
  if (status === "no_document") {
    return (
      <Badge variant="outline" className="whitespace-nowrap">
        <XCircle className="h-3 w-3" />
        No document
      </Badge>
    );
  }
  if (status === "duplicate_document") {
    return <Badge variant="warning">Previously replaced</Badge>;
  }
  return (
    <Badge variant="warning" dot>
      Needs review
    </Badge>
  );
}
