"use client";
import { Button } from "@/components/ui/button";
import { DocumentUploadPanel } from "./document-upload-panel";
import { DocumentFilenameConflictDialog, DocumentManualReviewDialog, DocumentWorkspaceUploadStatus } from "./document-workspace-bindings";
import type { DocumentWorkspaceController } from "../hooks/use-document-workspace";

export function DocumentWorkspaceUpload({ controller }: { controller: DocumentWorkspaceController }) {
  const {
    lane, review, verify, manualReview, filenameConflicts,
    upload, abortUploads, reupload, deleteDocuments, unassignDocuments,
    selectedFiles, verification, progress, progressDetail, stagingManifest,
    selectionError, setIsAbortUploadDialogOpen, phase, preparingCheck, reviewableFileIndexes,
    documentTypeOperationPending, processingUploadIds, canResumeCurrentUpload, hasIncompleteUploads, manualReviewLocked,
    manualReviewDisabled, acceptedFileCount, resetSelection, checkDocuments, startUpload,
    updateManualVerification,
  } = controller;
  return <>
      <DocumentUploadPanel
        lane={lane}
        passengerCount={review.data?.review_rows.length ?? 0}
        selectedFileCount={selectedFiles.length}
        acceptedFileCount={acceptedFileCount}
        verificationReady={Boolean(verification && stagingManifest)}
        hasIncompleteUploads={hasIncompleteUploads}
        canResumeCurrentUpload={canResumeCurrentUpload}
        processingUploadCount={processingUploadIds.length}
        uploadPending={upload.isPending}
        verifyPending={verify.isPending}
        abortPending={abortUploads.isPending}
        manualReviewPending={manualReview.pending || Boolean(manualReview.pendingUpload) || preparingCheck}
        onFilesSelected={resetSelection}
        onCheck={checkDocuments}
        onUpload={startUpload}
        onDiscardIncomplete={() => setIsAbortUploadDialogOpen(true)}
      />

      {filenameConflicts.conflict && (
        <DocumentFilenameConflictDialog
          key={filenameConflicts.conflict.selectedIndex}
          conflict={filenameConflicts.conflict}
          error={filenameConflicts.error}
          onDecision={filenameConflicts.choose}
          onCancel={filenameConflicts.cancel}
        />
      )}

      {preparingCheck && !filenameConflicts.conflict && !verify.isPending && (
        <p role="status" className="text-sm text-slate-600">Checking for existing filenames…</p>
      )}
      {manualReview.feedback && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{manualReview.feedback}</p>}
      {manualReview.error && !manualReview.reviewCandidates.length && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{manualReview.error}</p>}
      {manualReview.pendingUpload && !manualReview.pending && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="min-w-0 flex-1 text-sm text-amber-900">Approved PDFs have an unfinished upload. Resume it to finish only those selected files.</p>
          <Button onClick={() => void manualReview.resumeUpload(verification, updateManualVerification)} disabled={documentTypeOperationPending}>Resume approved upload</Button>
          <Button variant="secondary" onClick={() => void manualReview.discardUpload(verification, updateManualVerification)} disabled={documentTypeOperationPending}>Discard unfinished upload</Button>
        </div>
      )}
      {manualReview.pending && !manualReview.reviewCandidates.length && (
        <p role="status" className="text-sm text-blue-700">Uploading approved PDFs: {manualReview.progress?.uploaded ?? 0} of {manualReview.progress?.total ?? 0} completed.</p>
      )}

      {(upload.isPending || verify.isPending || phase !== "idle" || upload.error || selectionError || verify.error || reupload.error || deleteDocuments.error || unassignDocuments.error || verification) && (
        <DocumentWorkspaceUploadStatus
          phase={phase}
          progress={progress}
          progressDetail={progressDetail}
          uploadPending={upload.isPending}
          verifyPending={verify.isPending}
          uploadError={upload.error}
          selectionError={selectionError}
          verifyError={verify.error}
          reuploadError={reupload.error}
          deleteError={deleteDocuments.error}
          unassignError={unassignDocuments.error}
          verification={verification}
          reviewableFileIndexes={reviewableFileIndexes}
          manualReviewDisabled={manualReviewDisabled}
          manualReviewLocked={manualReviewLocked}
          onReviewFile={manualReview.openReview}
          selectedReviewFileIndexes={manualReview.selectedIndexes}
          onToggleReviewFile={manualReview.toggleSelection}
          onSelectAllReviewFiles={manualReview.selectAll}
          onReviewSelected={manualReview.openSelected}
        />
      )}

      {manualReview.reviewCandidates.length > 0 && verification && (
        <DocumentManualReviewDialog
          key={manualReview.reviewCandidates.map((candidate) => candidate.chunkId).join(":")}
          items={manualReview.reviewCandidates.map((candidate) => ({ fileIndex: candidate.fileIndex, file: candidate.file, reason: verification.files[candidate.fileIndex]?.reason ?? "Document type could not be identified." }))}
          lane={lane}
          pending={manualReview.pending}
          progress={manualReview.progress}
          error={manualReview.error}
          onClose={manualReview.closeReview}
          onApprove={() => {
            if (manualReviewDisabled) return;
            void manualReview.approve(verification, updateManualVerification);
          }}
        />
      )}
  </>;
}
