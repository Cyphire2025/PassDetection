"use client";

import { useRef } from "react";
import { ArrowLeft, FolderOpen, Plus, ScanText, UploadCloud } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useEcrWorkspace } from "../hooks/use-ecr-workspace";
import { ecrErrorMessage } from "../services/ecr-upload";
import { EcrResults, ecrBatchStatusLabel } from "./ecr-results";

export function EcrCheckerPage({ initialBatchId = null }: { initialBatchId?: string | null }) {
  const workspace = useEcrWorkspace(initialBatchId);
  const inputRef = useRef<HTMLInputElement>(null);
  const { batch, batches, batchId, busy, progress, entries, action } = workspace;
  const current = batch.data;
  const showUpload = !batchId || current?.status === "uploading";
  const allUploaded = current?.status === "uploading" && current.total_count === current.expected_count;
  const visibleError = workspace.error || (batch.error ? ecrErrorMessage(batch.error) : null);

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="ECR Checker"
        description="Upload passport back pages. Check for “Emigration Check Required” and export the file-by-file results."
        icon={ScanText}
        accent="amber"
        actions={(
          <IntentPrefetchLink href={ROUTES.dashboard.documents} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700">
            <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Documents
          </IntentPrefetchLink>
        )}
      />

      {batchId && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="secondary" onClick={() => workspace.selectBatch(null)} disabled={busy || action !== null}>
            <Plus className="h-4 w-4" aria-hidden="true" /> New batch / saved batches
          </Button>
          {current && <Badge variant="outline">{ecrBatchStatusLabel(current.status)}</Badge>}
        </div>
      )}

      {visibleError && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{visibleError}</div>}

      {batchId && batch.isLoading && <Skeleton className="h-56 rounded-xl" />}

      {showUpload && (
        <Card>
          <CardContent className="space-y-4 p-5 sm:p-6">
            <div>
              <h2 className="text-base font-semibold text-slate-950">{current ? current.title : "Upload passport back pages"}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Up to 1,000 JPG, PNG or WebP images, 10 MB each. Include the entire back page clearly, especially the top section.
              </p>
            </div>
            {!batchId && <Input label="Batch title (optional)" placeholder="Tomorrow’s passport checks" value={workspace.title} onChange={(event) => workspace.setTitle(event.target.value)} maxLength={160} disabled={busy} />}
            {current && !busy && !allUploaded && (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                {current.total_count} of {current.expected_count} images are saved. Select the same original images to resume; saved images will be skipped automatically.
              </p>
            )}
            {allUploaded && !busy && <p className="text-sm text-slate-600">All {current.expected_count} images are saved. Start the check to process this batch.</p>}
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
              multiple
              className="hidden"
              aria-label="Select passport back-page images"
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length) workspace.chooseFiles(files);
                event.currentTarget.value = "";
              }}
            />
            <div className="flex flex-wrap items-center gap-3">
              {!allUploaded && <Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={busy}><UploadCloud className="h-4 w-4" aria-hidden="true" />{batchId ? "Reselect images" : "Choose images"}</Button>}
              <Button onClick={() => void workspace.start()} disabled={busy || (!entries.length && !allUploaded)} isLoading={busy}>
                {busy ? "Uploading images…" : allUploaded ? "Start ECR check" : batchId ? "Resume upload & check" : "Upload & check ECR"}
              </Button>
              {entries.length > 0 && <span className="text-sm text-slate-600">{entries.length.toLocaleString()} images selected · {(entries.reduce((sum, entry) => sum + entry.file.size, 0) / 1024 / 1024).toFixed(1)} MB</span>}
            </div>
            {busy && (
              <div className="space-y-2 rounded-xl border border-blue-100 bg-blue-50 p-4" role="status" aria-live="polite">
                <div className="flex items-center justify-between gap-3 text-sm font-medium text-blue-950">
                  <span>{progress ? `${progress.completed} of ${progress.total} images saved` : "Preparing your batch…"}</span>
                  <span>{progress?.percent ?? 0}%</span>
                </div>
                <div role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress?.percent ?? 0} className="h-2 overflow-hidden rounded-full bg-white"><div className="h-full bg-blue-600 transition-all" style={{ width: `${progress?.percent ?? 0}%` }} /></div>
                <p className="text-xs text-blue-800">Keep this page open until uploads finish. The check then runs in the background, even if you leave this page.</p>
              </div>
            )}
            <p className="text-xs leading-5 text-slate-500">Images are checked concurrently. Unreadable or incomplete pages are flagged for review. Duplicate filenames are kept as separate rows.</p>
          </CardContent>
        </Card>
      )}

      {current && current.status !== "uploading" && <EcrResults key={current.batch_id} batch={current} action={action} onAction={workspace.performAction} />}

      {!batchId && (
        <Card>
          <CardContent className="p-0">
            <div className="border-b border-slate-100 p-5"><h2 className="text-base font-semibold text-slate-950">Saved checks</h2><p className="mt-1 text-sm text-slate-500">Reopen a batch to see live progress or download its Excel report.</p></div>
            {batches.isLoading ? <div className="p-5"><Skeleton className="h-24 rounded-xl" /></div> : batches.error ? <div role="alert" className="p-5 text-sm text-red-700">{ecrErrorMessage(batches.error)} <Button variant="link" onClick={() => void batches.refetch()}>Try again</Button></div> : !batches.data?.length ? <p className="p-5 text-sm text-slate-500">No ECR checks yet. Choose your images above to start.</p> : (
              <div className="divide-y divide-slate-100">
                {batches.data.map((saved) => (
                  <div key={saved.batch_id} className="flex flex-wrap items-center justify-between gap-4 p-5">
                    <div className="min-w-0 flex-1"><h3 className="break-words text-sm font-semibold text-slate-950">{saved.title}</h3><p className="mt-1 text-xs text-slate-500">{new Date(saved.created_at).toLocaleString()} · {saved.total_count}/{saved.expected_count} images · {ecrBatchStatusLabel(saved.status)}</p><p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs"><span className="font-semibold text-red-600">{saved.ecr_count} ECR</span><span className="text-black">{saved.na_count} NA</span><span className="text-amber-800">{saved.review_count} review</span><span className="text-slate-600">{saved.failed_count} failed</span></p></div>
                    <Button variant="outline" onClick={() => workspace.selectBatch(saved.batch_id)} disabled={busy}><FolderOpen className="h-4 w-4" aria-hidden="true" /> Open</Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
