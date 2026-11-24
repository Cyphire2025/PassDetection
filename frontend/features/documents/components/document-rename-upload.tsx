"use client";
import { UploadCloud } from "lucide-react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import { ProcessingMotion } from "@/components/shared/processing-motion";
import type { DocumentRenameWorkspace } from "../hooks/use-document-rename-workspace";

export function DocumentRenameUpload({ model }: { model: DocumentRenameWorkspace }) {
  const { title, setTitle, selectedFiles, setSelectedFiles, setResult, progress, setProgress,
    progressDetail, setProgressDetail, uploadSession, setUploadSession, setUploadSessionTitle,
    selectionError, setSelectionError, phase, inputRef, analyze, startAnalyze } = model;
  return (
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
  );
}
