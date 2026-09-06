"use client";

import { useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Archive,
  ArrowLeft,
  Download,
  FileCheck2,
  FileQuestion,
  FolderOpen,
  Plane,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { ProcessingMotion } from "@/components/shared/processing-motion";
import {
  WorkspaceHeaderContext,
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import type { RenameDocumentBatch, RenameDocumentBatchSummary } from "@/types/document-rename.types";
import {
  useAnalyzeRenameDocuments,
  useDeleteRenameBatches,
  useOpenRenameBatch,
  useRenameBatches,
} from "../hooks/use-document-rename";
import {
  createDocumentUploadSession,
  type DocumentUploadProgress,
  type DocumentUploadSession,
} from "../services/document-upload-batching";

type RenameFilter = "visa" | "flight_ticket" | "unknown";

function detectedLabel(value: string) {
  if (value === "visa") return "Visa";
  if (value === "flight_ticket") return "Flight Ticket";
  return "Rejected";
}

function detectedBadge(value: string) {
  if (value === "visa") return "success";
  if (value === "flight_ticket") return "secondary";
  return "warning";
}

export function DocumentRenamePage() {
  const [title, setTitle] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [result, setResult] = useState<RenameDocumentBatch | null>(null);
  const [selectedBatchIds, setSelectedBatchIds] = useState<string[]>([]);
  const [progress, setProgress] = useState(0);
  const [progressDetail, setProgressDetail] = useState<DocumentUploadProgress | null>(null);
  const [uploadSession, setUploadSession] = useState<DocumentUploadSession | null>(null);
  const [uploadSessionTitle, setUploadSessionTitle] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "analyzing">("idle");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const analyze = useAnalyzeRenameDocuments();
  const batches = useRenameBatches();
  const openBatch = useOpenRenameBatch();
  const deleteBatches = useDeleteRenameBatches();

  const startAnalyze = () => {
    if (selectedFiles.length === 0 || !title.trim()) return;
    let activeSession = uploadSession;
    let activeTitle = uploadSessionTitle;
    if (!activeSession) {
      try {
        activeSession = createDocumentUploadSession(selectedFiles);
        activeTitle = title.trim();
        setUploadSession(activeSession);
        setUploadSessionTitle(activeTitle);
      } catch (error) {
        setSelectionError(error instanceof Error ? error.message : "The selected PDFs are invalid");
        return;
      }
    }
    setSelectionError(null);
    setResult(null);
    setPhase("analyzing");
    setProgressDetail(null);
    setProgress(0);
    analyze.mutate(
      {
        title: activeTitle ?? title.trim(),
        files: selectedFiles,
        session: activeSession,
        onProgress: (value) => {
          setProgressDetail(value);
          setProgress(value.percent);
        },
      },
      {
        onSuccess: (data) => {
          setResult(data);
          setTitle("");
          setSelectedFiles([]);
          setUploadSession(null);
          setUploadSessionTitle(null);
          setProgressDetail(null);
          setProgress(100);
          setPhase("idle");
        },
        onError: () => setPhase("idle"),
      },
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="Rename Documents"
        description="Upload visa and ticket PDFs, review detected details, and download renamed files."
        icon={FileCheck2}
        accent="cyan"
        context={(
          <>
            <WorkspaceHeaderContext icon={Archive}>
              {(batches.data?.length ?? 0).toLocaleString()} saved {batches.data?.length === 1 ? "batch" : "batches"}
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={FileCheck2}>
              {selectedFiles.length.toLocaleString()} {selectedFiles.length === 1 ? "PDF" : "PDFs"} selected
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.documents}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Document Hub
          </IntentPrefetchLink>
        )}
      />

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Bulk Upload PDFs</h2>
              <p className="mt-1 text-sm text-slate-500">
                Upload mixed visa and flight-ticket PDFs. The system reads PDF text and prepares renamed downloads.
              </p>
            </div>
            <Badge variant="outline">{selectedFiles.length} selected</Badge>
          </div>

          <Input
            label="Batch title"
            placeholder="Thailand Group"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={analyze.isPending || uploadSession !== null}
          />

          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            className="hidden"
            onChange={(event) => {
              setSelectedFiles(Array.from(event.target.files ?? []));
              setResult(null);
              setUploadSession(null);
              setUploadSessionTitle(null);
              setSelectionError(null);
              setProgressDetail(null);
              setProgress(0);
              event.currentTarget.value = "";
            }}
          />

          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="secondary" onClick={() => inputRef.current?.click()} disabled={analyze.isPending}>
              <UploadCloud className="h-4 w-4" />
              Choose PDFs
            </Button>
            <Button type="button" onClick={startAnalyze} disabled={selectedFiles.length === 0 || !title.trim() || analyze.isPending}>
              Analyze And Rename {selectedFiles.length > 0 ? `(${selectedFiles.length})` : ""}
            </Button>
            {selectedFiles.length > 0 && (
              <span className="text-sm text-slate-500">{selectedFiles.length} file{selectedFiles.length === 1 ? "" : "s"} selected</span>
            )}
          </div>

          {(analyze.isPending || phase !== "idle") && (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 sm:flex-row sm:gap-5">
              {analyze.isPending && (
                <ProcessingMotion variant="rename" compact className="w-full shrink-0 sm:w-44" />
              )}
              <div className="w-full min-w-0 flex-1 space-y-3">
                <div className="flex items-center justify-between gap-3 text-sm font-medium text-blue-950" role="status">
                  <span>
                    {progressDetail?.phase === "processing" ? "Analysing and renaming PDFs" : "Uploading PDFs"}
                    {progressDetail
                      ? ` — ${progressDetail.completedFiles}/${progressDetail.totalFiles} complete`
                      : ""}
                  </span>
                  <span className="shrink-0 tabular-nums">{progress}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white">
                  <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
                </div>
              </div>
            </div>
          )}

          {(analyze.error || selectionError) && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {selectionError ?? analyze.error?.message}
              {analyze.error && progressDetail && progressDetail.completedFiles > 0
                ? ` ${progressDetail.completedFiles} of ${progressDetail.totalFiles} PDFs are safely committed; click Analyze And Rename again to resume.`
                : ""}
            </div>
          )}
        </CardContent>
      </Card>

      {analyze.isPending && !result ? null : result ? (
        <RenameResults batch={result} onBack={() => setResult(null)} />
      ) : (
        <SavedRenameBatches
          batches={batches.data ?? []}
          selectedBatchIds={selectedBatchIds}
          isLoading={batches.isLoading}
          isOpening={openBatch.isPending}
          isDeleting={deleteBatches.isPending}
          onSelectionChange={setSelectedBatchIds}
          onOpen={(batchId) =>
            openBatch.mutate(batchId, {
              onSuccess: (data) => setResult(data),
            })
          }
          onDelete={(batchIds) =>
            deleteBatches.mutate(batchIds, {
              onSuccess: () => {
                setSelectedBatchIds((current) => current.filter((batchId) => !batchIds.includes(batchId)));
              },
            })
          }
        />
      )}
    </div>
  );
}

function SavedRenameBatches({
  batches,
  selectedBatchIds,
  isLoading,
  isOpening,
  isDeleting,
  onSelectionChange,
  onOpen,
  onDelete,
}: {
  batches: RenameDocumentBatchSummary[];
  selectedBatchIds: string[];
  isLoading: boolean;
  isOpening: boolean;
  isDeleting: boolean;
  onSelectionChange: (batchIds: string[]) => void;
  onOpen: (batchId: string) => void;
  onDelete: (batchIds: string[]) => void;
}) {
  const visibleBatchIds = useMemo(() => batches.map((batch) => batch.batch_id), [batches]);
  const activeSelectedIds = selectedBatchIds.filter((batchId) => visibleBatchIds.includes(batchId));
  const allSelected = batches.length > 0 && activeSelectedIds.length === batches.length;

  const toggleBatch = (batchId: string) => {
    onSelectionChange(
      activeSelectedIds.includes(batchId)
        ? activeSelectedIds.filter((selectedId) => selectedId !== batchId)
        : [...activeSelectedIds, batchId],
    );
  };

  const toggleAll = () => {
    onSelectionChange(allSelected ? [] : visibleBatchIds);
  };

  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-col gap-4 border-b border-slate-100 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Saved Rename Batches</h2>
            <p className="mt-1 text-sm text-slate-500">Open any previous batch to download renamed PDFs again.</p>
          </div>
          {batches.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300 text-blue-600"
                  checked={allSelected}
                  onChange={toggleAll}
                  disabled={isDeleting}
                />
                Select all
              </label>
              <Button
                type="button"
                variant="danger"
                disabled={activeSelectedIds.length === 0 || isDeleting}
                isLoading={isDeleting && activeSelectedIds.length > 0}
                onClick={() => onDelete(activeSelectedIds)}
              >
                <Trash2 className="h-4 w-4" />
                Delete Selected {activeSelectedIds.length > 0 ? `(${activeSelectedIds.length})` : ""}
              </Button>
            </div>
          )}
        </div>
        {isLoading ? (
          <div className="p-5">
            <Skeleton className="h-28 rounded-xl" />
          </div>
        ) : batches.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">No rename batches yet.</div>
        ) : (
          <div className="divide-y divide-slate-100">
            {batches.map((batch, index) => (
              <div key={batch.batch_id} className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600"
                    checked={activeSelectedIds.includes(batch.batch_id)}
                    onChange={() => toggleBatch(batch.batch_id)}
                    disabled={isDeleting}
                    aria-label={`Select ${batch.title}`}
                  />
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-slate-900">
                      {index + 1}. {batch.title}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                      <span>{batch.total_count} PDFs</span>
                      <span>{batch.visa_count} {batch.visa_count === 1 ? "visa" : "visas"}</span>
                      <span>{batch.ticket_count} {batch.ticket_count === 1 ? "ticket" : "tickets"}</span>
                      <span>{batch.unknown_count} rejected</span>
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" disabled={isOpening} onClick={() => onOpen(batch.batch_id)}>
                    <FolderOpen className="h-4 w-4" />
                    Open
                  </Button>
                  {batch.status === "completed" && batch.visa_count + batch.ticket_count > 0 ? (
                    <a href={batch.zip_download_url} target="_blank" rel="noopener noreferrer">
                      <Button type="button" variant="secondary">
                        <Archive className="h-4 w-4" />
                        ZIP
                      </Button>
                    </a>
                  ) : batch.status === "processing" ? (
                    <span className="self-center text-xs font-medium text-amber-700">
                      Upload incomplete
                    </span>
                  ) : null}
                  <Button
                    type="button"
                    variant="danger"
                    disabled={isDeleting}
                    isLoading={isDeleting && activeSelectedIds.includes(batch.batch_id)}
                    onClick={() => onDelete([batch.batch_id])}
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RenameResults({ batch, onBack }: { batch: RenameDocumentBatch; onBack: () => void }) {
  const [filter, setFilter] = useState<RenameFilter>("visa");
  const hasDownloadableDocuments =
    batch.status === "completed" && batch.visa_count + batch.ticket_count > 0;
  const filteredItems = useMemo(
    () =>
      batch.items
        .filter((item) => item.detected_type === filter)
        .slice()
        .sort((first, second) => first.renamed_filename.localeCompare(second.renamed_filename)),
    [batch.items, filter],
  );

  return (
    <div className="space-y-3">
      <div>
        <Button type="button" variant="secondary" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="flex flex-col gap-4 border-b border-slate-100 p-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Rename Results</h2>
              <div className="mt-1 text-sm font-medium text-slate-700">{batch.title}</div>
              <p className="mt-1 text-sm text-slate-500">
                {batch.total_count} processed, {batch.visa_count} {batch.visa_count === 1 ? "visa" : "visas"}, {batch.ticket_count} flight {batch.ticket_count === 1 ? "ticket" : "tickets"}, {batch.unknown_count} rejected.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <FilterButton
                active={filter === "visa"}
                icon={<FileCheck2 className="h-3.5 w-3.5" />}
                activeClassName="border-green-200 bg-green-50 text-green-700"
                onClick={() => setFilter("visa")}
              >
                {batch.visa_count} {batch.visa_count === 1 ? "visa" : "visas"}
              </FilterButton>
              <FilterButton
                active={filter === "flight_ticket"}
                icon={<Plane className="h-3.5 w-3.5" />}
                activeClassName="border-blue-200 bg-blue-50 text-blue-700"
                onClick={() => setFilter("flight_ticket")}
              >
                {batch.ticket_count} {batch.ticket_count === 1 ? "ticket" : "tickets"}
              </FilterButton>
              <FilterButton
                active={filter === "unknown"}
                icon={<FileQuestion className="h-3.5 w-3.5" />}
                activeClassName="border-amber-200 bg-amber-50 text-amber-700"
                onClick={() => setFilter("unknown")}
              >
                {batch.unknown_count} rejected
              </FilterButton>
              {hasDownloadableDocuments ? (
                <a href={batch.zip_download_url} target="_blank" rel="noopener noreferrer">
                  <Button type="button">
                    <Archive className="h-4 w-4" />
                    Download ZIP
                  </Button>
                </a>
              ) : batch.status === "processing" ? (
                <span className="self-center text-xs font-medium text-amber-700">
                  Upload incomplete — resume the same selection to finish
                </span>
              ) : (
                <span className="self-center text-xs font-medium text-amber-700">
                  No verified PDFs to download
                </span>
              )}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Renamed document results</caption>
              <thead>
                <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                  <th scope="col" className="px-5 py-4">Original PDF</th>
                  <th scope="col" className="px-5 py-4">Renamed PDF</th>
                  <th scope="col" className="px-5 py-4">Detected</th>
                  <th scope="col" className="px-5 py-4">Extracted Name</th>
                  <th scope="col" className="px-5 py-4 text-right">Download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredItems.map((item) => {
                  const downloadable =
                    item.status !== "rejected" &&
                    (item.detected_type === "visa" || item.detected_type === "flight_ticket") &&
                    Boolean(item.download_url);
                  return (
                    <tr key={item.id}>
                      <td className="px-5 py-4">
                        <div className="font-medium text-slate-900">{item.original_filename}</div>
                        {item.reason && <div className="mt-1 text-xs text-amber-700">{item.reason}</div>}
                      </td>
                      <td className="px-5 py-4">
                        {downloadable ? (
                          <a href={item.download_url} className="font-medium text-blue-700 hover:underline">
                            {item.renamed_filename}
                          </a>
                        ) : (
                          <span className="font-medium text-slate-500">Not renamed</span>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        <Badge variant={detectedBadge(item.detected_type)}>
                          {detectedLabel(item.detected_type)}
                        </Badge>
                      </td>
                      <td className="px-5 py-4 text-slate-700">{item.extracted_name || "Not found"}</td>
                      <td className="px-5 py-4 text-right">
                        {downloadable ? (
                          <a href={item.download_url}>
                            <Button type="button" variant="outline" size="sm">
                              <Download className="h-4 w-4" />
                              File
                            </Button>
                          </a>
                        ) : (
                          <span className="text-xs font-medium text-slate-400">Rejected</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {filteredItems.length === 0 && (
              <div className="border-t border-slate-100 p-8 text-center text-sm text-slate-500">
                No documents in this category.
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function FilterButton({
  active,
  activeClassName,
  icon,
  children,
  onClick,
}: {
  active: boolean;
  activeClassName: string;
  icon: ReactNode;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-10 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition ${
        active ? activeClassName : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}
