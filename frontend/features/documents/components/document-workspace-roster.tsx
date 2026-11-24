"use client";
import { Card, CardContent, Skeleton } from "@/components/ui";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { DocumentBroadcastActions } from "./document-broadcast-actions";
import { updateSelectedDocumentIds } from "./document-workspace-model";
import { DocumentWorkspaceReviewControls, DocumentWorkspaceReviewRows } from "./document-workspace-bindings";
import type { DocumentWorkspaceController } from "../hooks/use-document-workspace";

export function DocumentWorkspaceRoster({ controller }: { controller: DocumentWorkspaceController }) {
  const {
    groupId, documentType, review, exportAssignments, reupload,
    manualUpload, deleteDocuments, save, setManualUploadTarget, hasIncompleteUploads,
    reviewModel, reviewCounts, assignmentIssues, visibleReviewRows, visibleAssignedDocumentIds,
    activeSelectedDocumentIdSet, activeSelectedAssignedDocumentIds, activeSelectedAssignedDocumentIdSet, activeSelectedUnmatchedDocumentIds, activeSelectedUnmatchedDocumentIdSet,
    allVisibleAssignmentsSelected, removalDocumentIds, removalPassengerCount, removalPending, physicalFileCount,
    assignedFileCount, assignedPassengerCount, needsAssignmentCount, showRowActions, pendingRemovalDocumentIds,
    setPendingRemovalDocumentIds, reviewFilter, setReviewFilter, reviewSearchQuery, setReviewSearchQuery,
    setSelectedDocumentIds, openDelivery,
  } = controller;
  return <>
      {review.isLoading ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <DocumentWorkspaceReviewControls
              assignedFileCount={assignedFileCount}
              assignedPassengerCount={assignedPassengerCount}
              needsAssignmentCount={needsAssignmentCount}
              rejectedCount={review.data?.rejected_count ?? 0}
              removalDocumentCount={removalDocumentIds.length}
              removalPassengerCount={removalPassengerCount}
              selectedAssignedDocumentCount={activeSelectedAssignedDocumentIds.length}
              selectedUnmatchedDocumentCount={activeSelectedUnmatchedDocumentIds.length}
              removalPending={removalPending}
              removalConfirmationPending={removalPending && pendingRemovalDocumentIds !== null}
              deleteUnassignedPending={deleteDocuments.isPending && pendingRemovalDocumentIds === null}
              saveDisabled={!review.data?.batch_id || review.data.status === "saved" || hasIncompleteUploads}
              savePending={save.isPending}
              saved={review.data?.status === "saved"}
              deliveryDisabled={!review.data?.batch_id || review.data.status !== "saved"}
              broadcastActions={<DocumentBroadcastActions groupId={groupId} documentType={documentType} documentsDisabled={!review.data?.batch_id || review.data.status !== "saved"} onSendDocuments={() => openDelivery()} />}
              exportPending={exportAssignments.isPending}
              exportError={exportAssignments.isError && !isDownloadCancelled(exportAssignments.error)}
              hasReviewData={Boolean(review.data)}
              physicalFileCount={physicalFileCount}
              assignmentIssues={assignmentIssues}
              selectedDocumentIdSet={activeSelectedDocumentIdSet}
              reviewCounts={reviewCounts}
              reviewFilter={reviewFilter}
              searchQuery={reviewSearchQuery}
              onRequestRemoval={() => setPendingRemovalDocumentIds(removalDocumentIds)}
              onDeleteUnassigned={() =>
                deleteDocuments.mutate(activeSelectedUnmatchedDocumentIds, {
                  onSuccess: () => {
                    setSelectedDocumentIds((current) =>
                      updateSelectedDocumentIds(
                        current,
                        activeSelectedUnmatchedDocumentIdSet,
                        false,
                      ),
                    );
                  },
                })
              }
              onSave={() =>
                review.data?.batch_id && save.mutate(review.data.batch_id)
              }
              onOpenDelivery={() => openDelivery()}
              onExport={() => {
                exportAssignments.reset();
                exportAssignments.mutate({
                  filter: reviewFilter,
                  search: reviewSearchQuery,
                });
              }}
              onToggleIssue={(documentId, selected) =>
                setSelectedDocumentIds((current) =>
                  updateSelectedDocumentIds(current, [documentId], selected),
                )
              }
              onReviewFilterChange={setReviewFilter}
              onClearSelectedAssignments={() =>
                setSelectedDocumentIds((current) =>
                  updateSelectedDocumentIds(
                    current,
                    activeSelectedAssignedDocumentIdSet,
                    false,
                  ),
                )
              }
              onSearchQueryChange={setReviewSearchQuery}
            />

            <div
              className="w-full overflow-x-auto overscroll-x-contain"
              role="region"
              aria-label="Passenger document review table"
              tabIndex={0}
            >
              <table className="w-full table-fixed min-w-[1120px] text-left text-sm">
                <caption className="sr-only">Assigned passenger documents</caption>
                <thead>
                  <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                    <th scope="col" className="w-12 px-3 py-4">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300"
                        aria-label="Select all visible assigned passengers"
                        checked={allVisibleAssignmentsSelected}
                        disabled={visibleAssignedDocumentIds.length === 0 || removalPending}
                        onChange={(event) =>
                          setSelectedDocumentIds((current) =>
                            updateSelectedDocumentIds(
                              current,
                              visibleAssignedDocumentIds,
                              event.target.checked,
                            ),
                          )
                        }
                      />
                    </th>
                    <th scope="col" className="w-[18%] px-3 py-4">Passenger</th>
                    <th scope="col" className="w-[11%] px-3 py-4">Passport</th>
                    <th scope="col" className="w-[25%] px-3 py-4">Document</th>
                    <th scope="col" className="w-[10%] px-3 py-4">Confidence</th>
                    <th scope="col" className="w-[12%] px-3 py-4">Status</th>
                    <th scope="col" className="w-[19%] px-3 py-4">Sent</th>
                    {showRowActions && <th scope="col" className="w-16 px-3 py-4 text-right">Action</th>}
                  </tr>
                </thead>
                <DocumentWorkspaceReviewRows
                  rows={visibleReviewRows}
                  documentsByPassengerId={reviewModel.documentsByPassengerId}
                  pdfCountsByPassengerId={reviewModel.pdfCountsByPassengerId}
                  activeSelectedAssignedDocumentIdSet={activeSelectedAssignedDocumentIdSet}
                  documentType={documentType}
                  showRowActions={showRowActions}
                  removalPending={removalPending}
                  reuploadPending={reupload.isPending || manualUpload.isPending}
                  onManualUpload={(row, mode) => { manualUpload.reset(); setManualUploadTarget({ row, mode }); }}
                  searchQuery={reviewSearchQuery}
                  onToggleRowDocuments={(documentIds, selected) =>
                    setSelectedDocumentIds((current) =>
                      updateSelectedDocumentIds(current, documentIds, selected),
                    )
                  }
                  onReupload={(passengerId, file) =>
                    reupload.mutate({ passengerId, file })
                  }
                  onRemoveAssignment={(documentId) =>
                    setPendingRemovalDocumentIds([documentId])
                  }
                  onResend={(documentId) => openDelivery([documentId], [documentId])}
                />
              </table>
            </div>

            {review.data && review.data.rejected_documents.length > 0 && (
              <div className="border-t border-slate-100 p-5">
                <h3 className="text-sm font-semibold text-slate-900">Rejected Files</h3>
                <div className="mt-3 grid gap-2">
                  {review.data.rejected_documents.map((file, index) => (
                    <div key={`${file.filename}:${index}`} className="flex items-center justify-between gap-3 rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm">
                      <span className="font-medium text-red-950">{file.filename}</span>
                      <span className="text-red-700">{file.reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </CardContent>
        </Card>
      )}
  </>;
}
