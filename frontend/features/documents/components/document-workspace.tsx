"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  FileQuestion,
  FileX2,
  MoreVertical,
  Plane,
  RefreshCw,
  Save,
  SearchCheck,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatConfidence } from "@/lib/utils/format";
import type { DistributionDocumentType, DocumentPassengerReviewRow, DocumentVerificationResult } from "@/types/document-distribution.types";
import {
  useDeleteDistributionDocuments,
  useDocumentGroups,
  useDocumentReview,
  useReuploadPassengerDocument,
  useSaveDocumentBatch,
  useUploadDistributionDocuments,
  useVerifyDistributionDocuments,
} from "../hooks/use-document-distribution";

const DOCUMENT_TYPES: Array<{
  type: DistributionDocumentType;
  title: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
}> = [
  { type: "visa", title: "Visa", description: "Upload visa PDFs for this group.", icon: FileCheck2 },
  { type: "flight_ticket", title: "Flight Ticket", description: "Upload e-tickets or itineraries.", icon: Plane },
  { type: "other", title: "Other", description: "Upload supporting travel documents.", icon: FileQuestion },
];

export function DocumentWorkspace({ groupId }: { groupId: string }) {
  const [selectedType, setSelectedType] = useState<DistributionDocumentType>("visa");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [verification, setVerification] = useState<DocumentVerificationResult | null>(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<"idle" | "checking" | "uploading">("idle");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { data: groups = [] } = useDocumentGroups();
  const group = groups.find((item) => item.group_id === groupId);
  const review = useDocumentReview(groupId, selectedType);
  const verify = useVerifyDistributionDocuments(groupId, selectedType);
  const upload = useUploadDistributionDocuments(groupId, selectedType);
  const reupload = useReuploadPassengerDocument(groupId, selectedType);
  const deleteDocuments = useDeleteDistributionDocuments(groupId, selectedType);
  const save = useSaveDocumentBatch(groupId, selectedType);
  const selectedConfig = DOCUMENT_TYPES.find((item) => item.type === selectedType) ?? DOCUMENT_TYPES[0];
  const missingCount = useMemo(() => (review.data?.review_rows ?? []).filter((row) => !row.document).length, [review.data]);
  const acceptedFiles = useMemo(() => {
    if (!verification) return [];
    const acceptedNames = new Set(verification.files.filter((file) => file.accepted).map((file) => file.filename));
    return selectedFiles.filter((file) => acceptedNames.has(file.name));
  }, [selectedFiles, verification]);
  const showRowActions = selectedType === "visa" || selectedType === "flight_ticket";
  const selectableDocumentIds = useMemo(
    () => (review.data?.review_rows ?? []).map((row) => row.document?.id).filter((id): id is string => Boolean(id)),
    [review.data],
  );
  const activeSelectedDocumentIds = selectedDocumentIds.filter((id) => selectableDocumentIds.includes(id));
  const allDocumentsSelected = selectableDocumentIds.length > 0 && activeSelectedDocumentIds.length === selectableDocumentIds.length;

  useEffect(() => {
    if (phase !== "checking" || !verify.isPending) return;
    const timer = window.setInterval(() => {
      setProgress((current) => (current >= 88 ? current : Math.min(current + 7, 88)));
    }, 220);
    return () => window.clearInterval(timer);
  }, [phase, verify.isPending]);

  const resetSelection = (files: File[]) => {
    setSelectedFiles(files);
    setVerification(null);
    setProgress(0);
    setPhase("idle");
  };

  const checkDocuments = () => {
    if (selectedFiles.length === 0) return;
    setPhase("checking");
    setProgress(8);
    verify.mutate(selectedFiles, {
      onSuccess: (data) => {
        setVerification(data);
        setProgress(100);
        setPhase("idle");
      },
      onError: () => {
        setPhase("idle");
      },
    });
  };

  const startUpload = () => {
    if (acceptedFiles.length === 0) return;
    setPhase("uploading");
    setProgress(0);
    upload.mutate(
      {
        files: acceptedFiles,
        onProgress: (value) => {
          setPhase("uploading");
          setProgress(value);
        },
      },
      {
        onSuccess: () => {
          setSelectedFiles([]);
          setVerification(null);
          setProgress(100);
          setPhase("idle");
        },
        onError: () => {
          setPhase("idle");
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title={group ? `${group.group_name} Documents` : "Group Documents"}
          description="Match uploaded documents to passengers and save the reviewed list."
        />
        <Link href={ROUTES.dashboard.documents as never}>
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" />
            Back to Groups
          </Button>
        </Link>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {DOCUMENT_TYPES.map((item) => {
          const Icon = item.icon;
          const active = selectedType === item.type;
          return (
            <button
              key={item.type}
              type="button"
              onClick={() => {
                setSelectedType(item.type);
                setSelectedFiles([]);
                setVerification(null);
                setSelectedDocumentIds([]);
                setProgress(0);
                setPhase("idle");
              }}
              className={`rounded-xl border bg-white p-5 text-left shadow-sm transition ${
                active ? "border-blue-300 ring-2 ring-blue-100" : "border-slate-200 hover:border-slate-300"
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={`flex h-10 w-10 items-center justify-center rounded-lg ${active ? "bg-blue-50 text-blue-700" : "bg-slate-50 text-slate-500"}`}>
                  <Icon className="h-5 w-5" />
                </span>
                <div>
                  <div className="font-semibold text-slate-900">{item.title}</div>
                  <div className="mt-1 text-sm text-slate-500">{item.description}</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Upload {selectedConfig.title} PDFs</h2>
              <p className="mt-1 text-sm text-slate-500">
                Select all {selectedConfig.title.toLowerCase()} files. The system checks document type before upload and matches files to passengers.
              </p>
            </div>
            <Badge variant="outline">{review.data?.review_rows.length ?? 0} passengers</Badge>
          </div>

          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            className="hidden"
            onChange={(event) => {
              resetSelection(Array.from(event.target.files ?? []));
              event.currentTarget.value = "";
            }}
          />

          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="secondary" onClick={() => inputRef.current?.click()} disabled={upload.isPending || verify.isPending}>
              <UploadCloud className="h-4 w-4" />
              Choose PDFs
            </Button>
            <Button type="button" variant="outline" onClick={checkDocuments} disabled={selectedFiles.length === 0 || upload.isPending || verify.isPending}>
              <SearchCheck className="h-4 w-4" />
              Check Documents {selectedFiles.length > 0 ? `(${selectedFiles.length})` : ""}
            </Button>
            <Button type="button" onClick={startUpload} disabled={!verification || acceptedFiles.length === 0 || upload.isPending || verify.isPending}>
              Upload Accepted {verification ? `(${acceptedFiles.length})` : ""}
            </Button>
            {selectedFiles.length > 0 && (
              <span className="text-sm text-slate-500">{selectedFiles.length} file{selectedFiles.length === 1 ? "" : "s"} selected</span>
            )}
          </div>

          {(upload.isPending || phase !== "idle") && (
            <div className="space-y-2 rounded-lg border border-blue-100 bg-blue-50 p-3">
              <div className="flex items-center justify-between text-sm font-medium text-blue-900">
                <span>{phase === "checking" ? "Checking documents uploaded" : "Uploading documents"}</span>
                <span>{progress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white">
                <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {upload.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {upload.error.message}
            </div>
          )}

          {verify.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {verify.error.message}
            </div>
          )}

          {reupload.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {reupload.error.message}
            </div>
          )}

          {deleteDocuments.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {deleteDocuments.error.message}
            </div>
          )}

          {verification && (
            <VerificationPanel verification={verification} />
          )}
        </CardContent>
      </Card>

      {review.isLoading ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="flex flex-col gap-3 border-b border-slate-100 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-base font-semibold text-slate-900">Review Matches</h2>
                <p className="mt-1 text-sm text-slate-500">
                  {review.data?.matched_count ?? 0} matched, {missingCount} missing, {review.data?.rejected_count ?? 0} rejected.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="danger"
                  disabled={activeSelectedDocumentIds.length === 0 || deleteDocuments.isPending}
                  isLoading={deleteDocuments.isPending}
                  onClick={() =>
                    deleteDocuments.mutate(activeSelectedDocumentIds, {
                      onSuccess: () => setSelectedDocumentIds([]),
                    })
                  }
                >
                  <Trash2 className="h-4 w-4" />
                  Delete Selected {activeSelectedDocumentIds.length > 0 ? `(${activeSelectedDocumentIds.length})` : ""}
                </Button>
                <Button
                  type="button"
                  disabled={!review.data?.batch_id || review.data.status === "saved"}
                  isLoading={save.isPending}
                  onClick={() => review.data?.batch_id && save.mutate(review.data.batch_id)}
                >
                  <Save className="h-4 w-4" />
                  {review.data?.status === "saved" ? "Saved" : "Save List"}
                </Button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                    <th className="px-5 py-4">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300"
                        aria-label="Select all documents"
                        checked={allDocumentsSelected}
                        disabled={selectableDocumentIds.length === 0 || deleteDocuments.isPending}
                        onChange={(event) => {
                          setSelectedDocumentIds(event.target.checked ? selectableDocumentIds : []);
                        }}
                      />
                    </th>
                    <th className="px-5 py-4">Passenger</th>
                    <th className="px-5 py-4">Passport</th>
                    <th className="px-5 py-4">Document</th>
                    <th className="px-5 py-4">Confidence</th>
                    <th className="px-5 py-4">Status</th>
                    {showRowActions && <th className="px-5 py-4 text-right">Action</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(review.data?.review_rows ?? []).map((row) => (
                    <tr key={row.passenger_id}>
                      <td className="px-5 py-4">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300"
                          aria-label={`Select document for ${row.passenger_name}`}
                          checked={Boolean(row.document?.id && activeSelectedDocumentIds.includes(row.document.id))}
                          disabled={!row.document || deleteDocuments.isPending}
                          onChange={(event) => {
                            const documentId = row.document?.id;
                            if (!documentId) return;
                            setSelectedDocumentIds((current) =>
                              event.target.checked
                                ? Array.from(new Set([...current, documentId]))
                                : current.filter((id) => id !== documentId),
                            );
                          }}
                        />
                      </td>
                      <td className="px-5 py-4">
                        <div className="font-semibold text-slate-900">{row.passenger_name}</div>
                        <div className="mt-1 text-xs text-slate-500">{row.departure_city || "No departure city"}</div>
                      </td>
                      <td className="px-5 py-4 text-slate-700">{row.passport_number || "Not set"}</td>
                      <td className="px-5 py-4">
                        {row.document ? (
                          <a href={row.document.url ?? "#"} target="_blank" rel="noreferrer" className="font-medium text-blue-700 hover:underline">
                            {row.document.original_filename}
                          </a>
                        ) : (
                          <span className="text-slate-400">Empty</span>
                        )}
                      </td>
                      <td className="px-5 py-4 text-slate-700">{row.document ? formatConfidence(row.document.match_confidence) : "-"}</td>
                      <td className="px-5 py-4">
                        <MatchBadge status={row.document?.match_status ?? "no_document"} />
                      </td>
                      {showRowActions && (
                        <td className="px-5 py-4 text-right">
                          <DocumentRowActionMenu
                            row={row}
                            documentType={selectedType}
                            pending={reupload.isPending}
                            onReupload={(file) => reupload.mutate({ passengerId: row.passenger_id, file })}
                          />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {review.data && review.data.rejected_documents.length > 0 && (
              <div className="border-t border-slate-100 p-5">
                <h3 className="text-sm font-semibold text-slate-900">Rejected Files</h3>
                <div className="mt-3 grid gap-2">
                  {review.data.rejected_documents.map((file) => (
                    <div key={file.filename} className="flex items-center justify-between gap-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm">
                      <span className="font-medium text-red-950">{file.filename}</span>
                      <span className="text-red-700">{file.reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {review.data && review.data.unmatched_documents.length > 0 && (
              <div className="border-t border-slate-100 p-5">
                <h3 className="text-sm font-semibold text-slate-900">Needs Manual Review</h3>
                <div className="mt-3 grid gap-2">
                  {review.data.unmatched_documents.map((document) => (
                    <div key={document.id} className="flex items-center justify-between gap-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-sm">
                      <span className="font-medium text-amber-950">{document.original_filename}</span>
                      <span className="text-amber-700">{document.match_reason || document.match_status}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function VerificationPanel({ verification }: { verification: DocumentVerificationResult }) {
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

function VerificationMatchText({ file }: { file: DocumentVerificationResult["files"][number] }) {
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

function DocumentRowActionMenu({
  row,
  documentType,
  pending,
  onReupload,
}: {
  row: DocumentPassengerReviewRow;
  documentType: DistributionDocumentType;
  pending: boolean;
  onReupload: (file: File) => void;
}) {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const label = documentType === "flight_ticket" ? "flight ticket" : "visa";

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
        <div role="menu" className="absolute right-0 top-10 z-30 w-48 rounded-lg border border-slate-200 bg-white py-1 text-left shadow-lg">
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            onClick={() => inputRef.current?.click()}
          >
            <RefreshCw className="h-4 w-4" />
            Reupload document
          </button>
          <div className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
            Upload one {label} PDF for this passenger.
          </div>
        </div>
      )}
    </div>
  );
}

function MatchBadge({ status }: { status: string }) {
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
  return (
    <Badge variant="warning" dot>
      Needs review
    </Badge>
  );
}
