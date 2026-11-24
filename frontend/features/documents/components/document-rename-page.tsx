"use client";
import { Archive, ArrowLeft, FileCheck2 } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspaceHeaderContext, WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";
import { Button } from "@/components/ui";
import { useDocumentRenameWorkspace } from "../hooks/use-document-rename-workspace";
import { DocumentRenameUpload } from "./document-rename-upload";
import { SavedRenameBatches } from "./saved-rename-batches";
import { RenameResults } from "./rename-results";

export function DocumentRenamePage() {
  const model = useDocumentRenameWorkspace();
  const { batches, selectedFiles, analyze, result, setResult, selectedBatchIds, openBatch,
    deleteBatches, setSelectedBatchIds } = model;
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

      <DocumentRenameUpload model={model} />

      {batches.error && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        <span>Saved batches could not be refreshed. {batches.error.message}</span>
        <Button type="button" variant="secondary" disabled={batches.isFetching} onClick={() => void batches.refetch()}>Retry saved batches</Button>
      </div>}
      {(openBatch.error || deleteBatches.error) && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {openBatch.error ? `The batch could not be opened. ${openBatch.error.message}` : `The batch could not be deleted. ${deleteBatches.error?.message}`}
      </div>}

      {analyze.isPending && !result ? null : result ? (
        <RenameResults batch={result} onBack={() => setResult(null)} />
      ) : (
        <SavedRenameBatches
          batches={batches.data ?? []}
          selectedBatchIds={selectedBatchIds}
          isLoading={batches.isLoading}
          loadError={batches.error}
          isOpening={openBatch.isPending}
          isDeleting={deleteBatches.isPending}
          onSelectionChange={setSelectedBatchIds}
          onOpen={(batchId) => {
            deleteBatches.reset();
            openBatch.mutate(batchId, {
              onSuccess: (data) => setResult(data),
            });
          }}
          onDelete={(batchIds) => {
            openBatch.reset();
            deleteBatches.mutate(batchIds, {
              onSuccess: () => {
                setSelectedBatchIds((current) => current.filter((batchId) => !batchIds.includes(batchId)));
              },
            });
          }}
        />
      )}
    </div>
  );
}
