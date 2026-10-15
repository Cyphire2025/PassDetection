"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, ConfirmDialog } from "@/components/ui";
import type { DocumentPassengerReviewRow, DistributionDocumentType } from "@/types/document-distribution.types";
import type { WhatsAppLinkedClientGroup } from "@/features/whatsapp/api/whatsapp.api";
import { documentUpdatesApi } from "../api/document-updates.api";
import { DOCUMENT_DISTRIBUTION_LANES, distributionDocumentLabel } from "../config/document-distribution-lanes";
import { useDocumentReview, useManualPassengerDocumentUpload, useUnassignDistributionDocuments } from "../hooks/use-document-distribution";
import { createDocumentReviewModel, filterDocumentReviewRows, updateSelectedDocumentIds, type ReviewFilter } from "./document-workspace-model";
import { DocumentWorkspaceReviewRows } from "./document-workspace-review-rows";
import { ManualPassengerDocumentDialog } from "./manual-passenger-document-dialog";
import { DocumentBroadcastActions } from "./document-broadcast-actions";
import { DocumentRecipientSendDialog } from "./document-recipient-send-dialog";
import { DocumentUpdateStatus, hasPendingDocumentUpdates } from "./document-update-status";

const FILTERS: [ReviewFilter, string][] = [["all", "All"], ["multiple_pdfs", "Multiple PDFs"], ["shared_pdf", "Shared PDF"], ["assigned", "Assigned"], ["missing", "Missing"], ["sent", "Sent"], ["not_sent", "Not sent"]];

export function DocumentRecipientPanel({ broadcastGroupId, groups, readOnly = false }: {
  broadcastGroupId: string; groups: WhatsAppLinkedClientGroup[]; readOnly?: boolean;
}) {
  const [selectedGroup, setSelectedGroup] = useState("");
  const [lane, setLane] = useState<DistributionDocumentType>("visa");
  const groupId = groups.some(group => group.id === selectedGroup) ? selectedGroup : groups[0]?.id;
  if (!groupId) return <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600">Link a client group to this broadcast to manage its passenger documents.</p>;
  return <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
    <h3 className="text-lg font-semibold">Passenger documents</h3>
    <div className="flex flex-wrap gap-4">
      <label className="text-sm font-medium">Client group<select aria-label="Document client group" className="ml-2 rounded-lg border border-slate-300 p-2" value={groupId} onChange={event => setSelectedGroup(event.target.value)}>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label>
      <label className="text-sm font-medium">Document type<select aria-label="Document type" className="ml-2 rounded-lg border border-slate-300 p-2" value={lane} onChange={event => setLane(event.target.value as DistributionDocumentType)}>{Object.values(DOCUMENT_DISTRIBUTION_LANES).map(item => <option key={item.documentType} value={item.documentType}>{item.title}</option>)}</select></label>
    </div>
    <DocumentRecipientLane key={`${broadcastGroupId}:${groupId}:${lane}`} groupId={groupId} documentType={lane} broadcastGroupId={broadcastGroupId} readOnly={readOnly} />
  </section>;
}

function DocumentRecipientLane({ groupId, documentType, broadcastGroupId, readOnly }: {
  groupId: string; documentType: DistributionDocumentType; broadcastGroupId: string; readOnly: boolean;
}) {
  const review = useDocumentReview(groupId, documentType);
  // This server-resolved list includes missing, failed and uncertain documents.
  // UI filtering is not the send authorization: scoped preview/send revalidate.
  const scope = useQuery({ queryKey: ["document-update-preview", groupId, documentType, broadcastGroupId], queryFn: ({ signal }) => documentUpdatesApi.preview(groupId, documentType, broadcastGroupId, signal), staleTime: 0, refetchInterval: query => hasPendingDocumentUpdates(query.state.data?.recipients) ? 5000 : false });
  const manual = useManualPassengerDocumentUpload(groupId, documentType);
  const unassign = useUnassignDistributionDocuments(groupId, documentType);
  const [target, setTarget] = useState<{ row: DocumentPassengerReviewRow; mode: "add" | "replace" } | null>(null);
  const [filter, setFilter] = useState<ReviewFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [sendTarget, setSendTarget] = useState<{ initialResendId?: string; initialDocumentIds?: string[] } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const model = useMemo(() => {
    if (!review.data || !scope.data) return createDocumentReviewModel(undefined);
    const allowed = new Set(scope.data.recipients.map(row => row.passenger_id));
    return createDocumentReviewModel({ ...review.data, review_rows: review.data.review_rows.filter(row => allowed.has(row.passenger_id)), unmatched_documents: [], assignment_issues: [] });
  }, [review.data, scope.data]);
  const rows = filterDocumentReviewRows(model, filter, search);
  if (review.isLoading || scope.isLoading) return <p role="status">Loading passenger documents…</p>;
  if (review.error || scope.error) return <div role="alert"><p>Passenger documents could not be loaded.</p><Button onClick={() => { void review.refetch(); void scope.refetch(); }}>Try again</Button></div>;
  return <>
    <p className="text-sm text-slate-600">Documents for passengers linked to this broadcast. Shared PDF counts also consider other passengers in the same client group.</p>
    {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
    <div className="flex flex-wrap items-center gap-2">
      {FILTERS.map(([value, label]) => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)} className={`rounded-full border px-3 py-1.5 text-sm ${filter === value ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 text-slate-600"}`}>{label} ({model.counts[value]})</button>)}
      <div className="ml-auto">{!readOnly && <DocumentBroadcastActions groupId={groupId} documentType={documentType} broadcastGroupId={broadcastGroupId} documentsDisabled={!model.counts.assigned || review.data?.status !== "saved"} onSendDocuments={() => setSendTarget({ initialDocumentIds: selectedIds.length ? selectedIds : undefined })} />}</div>
      <label className="w-full"><span className="sr-only">Search passenger documents</span><input type="search" aria-label="Search passenger documents" placeholder="Search passenger name" value={search} onChange={event => setSearch(event.target.value)} className="w-full rounded-lg border border-slate-300 p-2 text-sm sm:max-w-md" /></label>
    </div>
    <div role="region" aria-label="Broadcast passenger documents" tabIndex={0} className="overflow-x-auto">
      <table className="w-full min-w-[1060px] table-fixed text-left text-sm">
        <caption className="sr-only">Document assignments and sending status for this broadcast</caption>
        <thead><tr className="border-b text-xs uppercase text-slate-500"><th scope="col" className="w-10"><span className="sr-only">Selection</span></th><th scope="col" className="w-[18%] p-3">Passenger</th><th scope="col" className="w-[11%] p-3">Passport</th><th scope="col" className="w-[24%] p-3">Document</th><th scope="col" className="w-[10%] p-3">Confidence</th><th scope="col" className="w-[12%] p-3">Status</th><th scope="col" className="w-[18%] p-3">Sent</th>{!readOnly && <th scope="col" className="w-16 p-3">Action</th>}</tr></thead>
        <DocumentWorkspaceReviewRows rows={rows} documentsByPassengerId={model.documentsByPassengerId} pdfCountsByPassengerId={model.pdfCountsByPassengerId} activeSelectedAssignedDocumentIdSet={new Set(selectedIds)} documentType={documentType} showRowActions={!readOnly} removalPending={unassign.isPending || readOnly} reuploadPending={manual.isPending} allowResend={!readOnly} searchQuery={search} onToggleRowDocuments={(ids, checked) => setSelectedIds(current => updateSelectedDocumentIds(current, ids, checked))} onReupload={() => undefined} onManualUpload={(row, mode) => { manual.reset(); setTarget({ row, mode }); }} onRemoveAssignment={id => { unassign.reset(); setRemoveId(id); }} onResend={id => { if (!readOnly) setSendTarget({ initialResendId: id }); }} />
      </table>
    </div>
    {!model.counts.all && <p className="text-sm text-slate-600">No passengers in this client group could be linked uniquely to this broadcast. Check the linked traveller records.</p>}
    <details className="rounded-lg border border-slate-200 p-3">
      <summary className="cursor-pointer font-medium">{distributionDocumentLabel(documentType)} update messages ({scope.data?.recipients.filter(row => row.latest_update_status).length ?? 0})</summary>
      <div className="mt-3 space-y-3">
        <p className="text-sm text-slate-600">Latest text update for each traveller in this section. These outcomes are separate from their PDF sending status.</p>
        <Button variant="secondary" disabled={scope.isFetching} onClick={() => { void scope.refetch(); }}>Refresh update status</Button>
        {scope.data?.recipients.filter(row => row.latest_update_status).map(row => <div key={row.passenger_id} className="rounded-lg bg-slate-50 p-3"><p className="font-medium">{row.passenger_name}</p><DocumentUpdateStatus recipient={row} /></div>)}
        {!scope.data?.recipients.some(row => row.latest_update_status) && <p className="text-sm text-slate-600">No text updates have been sent in this section.</p>}
      </div>
    </details>
    {target && <ManualPassengerDocumentDialog row={target.row} mode={target.mode} pending={manual.isPending} error={manual.error?.message ?? null} onClose={() => { if (!manual.isPending) setTarget(null); }} onUpload={(file, replacements) => manual.mutate({ passengerId: target.row.passenger_id, mode: target.mode, replacements, file }, { onSuccess: () => setTarget(null) })} />}
    <ConfirmDialog isOpen={Boolean(removeId)} title="Remove this assignment?" description="The PDF remains saved for review. Other passengers keep their assignments." confirmLabel="Remove assignment" cancelLabel="Cancel" isLoading={unassign.isPending} onClose={() => { if (!unassign.isPending) setRemoveId(null); }} onConfirm={() => { if (removeId) unassign.mutate([removeId], { onSuccess: () => setRemoveId(null) }); }} />
    {unassign.error && <p role="alert" className="text-sm text-red-700">{unassign.error.message}</p>}
    {sendTarget && <DocumentRecipientSendDialog groupId={groupId} documentType={documentType} broadcastGroupId={broadcastGroupId} initialResendId={sendTarget.initialResendId} initialDocumentIds={sendTarget.initialDocumentIds} onClose={() => setSendTarget(null)} onSent={message => { setNotice(message); setSendTarget(null); void review.refetch(); }} />}
  </>;
}
