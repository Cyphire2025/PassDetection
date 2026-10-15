"use client";

import { useId, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { CompanyReference } from "../types";
import { CompanyError, CompanyLoading, companyErrorMessage } from "./company-feedback";

interface ReassignmentPreview {
  group_id: string;
  source_company_id: string | null;
  target_company_id: string;
  expected_revision: number;
  expected_roster_revision: number;
  submission_records: number;
  accepted_participations: number;
  active_claims: number;
  active_grants: number;
  manager_conflict: boolean;
  can_reassign: boolean;
}

export function CompanyReassignmentDialog({ group, target, onSuccess, onClose }: {
  group: UploadLinkResponse;
  target: CompanyReference;
  onSuccess: (response: UploadLinkResponse) => Promise<void>;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const endpoint = API_ENDPOINTS.companies.reassignment(target.id, group.id);
  const scope = { agency_id: group.agency_id };
  const preview = useQuery({ queryKey: ["companies", group.agency_id, target.id, "reassignment", group.id], queryFn: async ({ signal }) => (await apiClient.get<ReassignmentPreview>(`${endpoint}/preview`, { params: scope, signal })).data, retry: 1, gcTime: 0, staleTime: 0 });
  const save = useMutation({ mutationFn: async () => {
    if (!preview.data?.can_reassign) throw new Error("Refresh the reassignment preview before continuing.");
    return (await apiClient.post<UploadLinkResponse>(endpoint, { expected_revision: preview.data.expected_revision, expected_roster_revision: preview.data.expected_roster_revision, reason: reason.trim() }, { params: scope })).data;
  }, onSuccess: async (response) => { await onSuccess(response); onClose(); } });
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !save.isPending, onClose });
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={handleKeyDown} className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/60 p-4">
    <section className="max-h-[90dvh] w-full max-w-xl space-y-4 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl">
      <h2 id={titleId} className="text-lg font-semibold text-slate-950">Review company reassignment</h2>
      <p className="break-words text-sm leading-6 text-slate-600">Move {group.name} from {group.company?.name ?? "its current company"} to <strong>{target.name}</strong>.</p>
      {preview.isLoading ? <CompanyLoading /> : preview.isError ? <CompanyError message="The impact preview could not be loaded." retry={() => void preview.refetch()} /> : preview.data && <>
        <dl className="grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-4 text-sm">{([
          ["Submission records", preview.data.submission_records], ["Accepted participations", preview.data.accepted_participations], ["Active claims", preview.data.active_claims], ["History grants", preview.data.active_grants],
        ] as const).map(([label, count]) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-semibold text-slate-900">{count.toLocaleString()}</dd></div>)}</dl>
        <p className="text-xs leading-5 text-slate-600">Affected history access will be revoked. Existing traveller profiles and completed trip snapshots keep their provenance. Records in the destination company require reconciliation before historical reuse.</p>
        {preview.data.manager_conflict && <CompanyError message="A client-manager assignment conflicts with this company. Resolve the manager assignment before reassigning." />}
        {!preview.data.can_reassign && !preview.data.manager_conflict && <CompanyError message="This group cannot be reassigned in its current state." />}
        <label className="block space-y-2 text-sm font-medium text-slate-700">Reason for reassignment<textarea rows={3} minLength={10} maxLength={500} required value={reason} onChange={(event) => setReason(event.target.value)} disabled={save.isPending} className="block w-full rounded-xl border border-slate-300 p-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600" placeholder="Explain why this group belongs to the selected company." /></label>
      </>}
      {save.isError && <CompanyError message={companyErrorMessage(save.error, "Reassignment could not be saved. Refresh the preview before trying again.")} retry={() => { save.reset(); void preview.refetch(); }} />}
      <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4"><Button type="button" variant="secondary" disabled={save.isPending} onClick={onClose} data-dialog-initial-focus>Cancel</Button><Button type="button" disabled={!preview.data?.can_reassign || preview.isFetching || reason.trim().length < 10} isLoading={save.isPending} onClick={async () => { if (inFlight.current) return; inFlight.current = true; try { await save.mutateAsync(); } catch { /* Render server conflict without losing the entered reason. */ } finally { inFlight.current = false; } }}>Confirm reassignment</Button></div>
    </section>
  </div>;
}
