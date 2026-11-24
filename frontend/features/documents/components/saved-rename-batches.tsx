"use client";
import { useMemo } from "react";
import { Archive, FolderOpen, Trash2 } from "lucide-react";
import { Button, Card, CardContent, Skeleton, buttonVariants } from "@/components/ui";
import type { RenameDocumentBatchSummary } from "@/types/document-rename.types";
import { cn } from "@/lib/utils/cn";

export function SavedRenameBatches({
  batches,
  selectedBatchIds,
  isLoading,
  loadError,
  isOpening,
  isDeleting,
  onSelectionChange,
  onOpen,
  onDelete,
}: {
  batches: RenameDocumentBatchSummary[];
  selectedBatchIds: string[];
  isLoading: boolean;
  loadError?: Error | null;
  isOpening: boolean;
  isDeleting: boolean;
  onSelectionChange: (batchIds: string[]) => void;
  onOpen: (batchId: string) => void;
  onDelete: (batchIds: string[]) => void;
}) {
  const visibleBatchIds = useMemo(() => batches.map((batch) => batch.batch_id), [batches]);
  const visibleBatchIdSet = useMemo(() => new Set(visibleBatchIds), [visibleBatchIds]);
  const activeSelectedIds = useMemo(
    () => selectedBatchIds.filter((batchId) => visibleBatchIdSet.has(batchId)),
    [selectedBatchIds, visibleBatchIdSet],
  );
  const activeSelectedIdSet = useMemo(() => new Set(activeSelectedIds), [activeSelectedIds]);
  const allSelected = batches.length > 0 && activeSelectedIds.length === batches.length;

  const toggleBatch = (batchId: string) => {
    onSelectionChange(
      activeSelectedIdSet.has(batchId)
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
        ) : loadError && batches.length === 0 ? null : batches.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">No rename batches yet.</div>
        ) : (
          <div className="divide-y divide-slate-100">
            {batches.map((batch, index) => (
              <div key={batch.batch_id} className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600"
                    checked={activeSelectedIdSet.has(batch.batch_id)}
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
                    <a href={batch.zip_download_url} target="_blank" rel="noopener noreferrer" className={cn(buttonVariants({ variant: "secondary" }))}>
                      <Archive className="h-4 w-4" />
                      ZIP
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
                    isLoading={isDeleting && activeSelectedIdSet.has(batch.batch_id)}
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
