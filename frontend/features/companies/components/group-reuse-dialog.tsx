"use client";

import { useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { reuseSetupApi, type GroupReuseConfig } from "../api/reuse-setup.api";
import { companyKeys } from "../hooks/use-companies";
import type { CompanyGroup } from "../types";
import { CompanyError, CompanyLoading, companyErrorMessage } from "./company-feedback";

export function GroupReuseDialog({ agencyId, companyId, group, onClose }: { agencyId: string; companyId: string; group: CompanyGroup; onClose: () => void }) {
  const query = useQuery({ queryKey: [...companyKeys.scope(agencyId), companyId, group.id, "reuse-config"], queryFn: ({ signal }) => reuseSetupApi.group(agencyId, companyId, group.id, signal), staleTime: 0, gcTime: 0, retry: 1 });
  const [pending, setPending] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const title = useId();
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"><section className="max-h-[90dvh] w-full max-w-lg space-y-4 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl"><div className="flex items-start justify-between gap-3"><div><h2 id={title} className="text-lg font-semibold text-slate-950">Group reuse settings</h2><p className="mt-1 break-words text-sm text-slate-500">{group.name}</p></div><Button type="button" variant="ghost" disabled={pending} onClick={onClose}>Close</Button></div>{query.isLoading ? <CompanyLoading /> : query.isError || !query.data ? <CompanyError message="Group reuse settings could not be loaded." retry={() => void query.refetch()} /> : <GroupConfigForm agencyId={agencyId} companyId={companyId} config={query.data} eligible={group.status === "active" && !group.import_only} onPending={setPending} onSaved={onClose} />}</section></div>;
}

function GroupConfigForm({ agencyId, companyId, config, eligible, onPending, onSaved }: { agencyId: string; companyId: string; config: GroupReuseConfig; eligible: boolean; onPending: (value: boolean) => void; onSaved: () => void }) {
  const [enabled, setEnabled] = useState(config.enabled);
  const [mode, setMode] = useState(config.roster_mode);
  const [identifier, setIdentifier] = useState(config.individual_identifier_type ?? "");
  const [required, setRequired] = useState(config.identifier_required);
  const client = useQueryClient();
  const mutation = useMutation({ mutationFn: () => reuseSetupApi.saveGroup(agencyId, companyId, config.group_id, { expected_revision: config.revision, expected_group_revision: config.group_revision, enabled, roster_mode: mode, individual_identifier_type: identifier.trim() || null, identifier_required: required }), onMutate: () => onPending(true), onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }), client.invalidateQueries({ queryKey: ["upload-links"] })]); onSaved(); }, onSettled: () => onPending(false) });
  return <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!mutation.isPending) mutation.mutate(); }}><fieldset disabled={mutation.isPending} className="space-y-4">
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" className="mt-1" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={!eligible && !enabled} />Enable verified reuse for this group</label>
    {!eligible && <p className="text-sm text-amber-800">Reuse can be enabled for active collection groups.</p>}
    <label className="block space-y-2 text-sm font-medium text-slate-700">Traveller roster<select aria-label="Traveller roster" className="min-h-11 w-full rounded-xl border border-slate-300 px-3" value={mode} onChange={(event) => setMode(event.target.value as GroupReuseConfig["roster_mode"])}><option value="closed">Closed · invited travellers only</option><option value="open">Open · verified company travellers</option></select></label>
    <p className="text-xs leading-5 text-slate-500">Closed groups require an authorised roster entry. Open groups allow verified company travellers to submit for this trip.</p>
    <Input label="Individual code type (optional)" value={identifier} onChange={(event) => setIdentifier(event.target.value)} maxLength={64} pattern="[a-z][a-z0-9_]*" hint="Use the existing individual identifier type, such as staff_code. Shared account codes cannot identify a person." />
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" className="mt-1" checked={required} onChange={(event) => setRequired(event.target.checked)} />Require this individual identifier</label>
  </fieldset>{mutation.isError && <CompanyError message={companyErrorMessage(mutation.error, "The group changed or reuse is not yet configured. Refresh and try again.")} />}<Button type="submit" isLoading={mutation.isPending} disabled={(enabled && !eligible) || (required && !identifier.trim())}>Save group reuse settings</Button></form>;
}
