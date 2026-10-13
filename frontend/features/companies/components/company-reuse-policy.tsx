"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { reuseSetupApi, type ReusePolicy } from "../api/reuse-setup.api";
import { companyKeys } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, companyErrorMessage } from "./company-feedback";

/** Policy is fetched only when opened; group rows never fan out policy requests. */
export function CompanyReusePolicy({ agencyId, companyId, active }: { agencyId: string; companyId: string; active: boolean }) {
  const [open, setOpen] = useState(false);
  const policy = useQuery({ queryKey: [...companyKeys.scope(agencyId), companyId, "reuse-policy"], queryFn: ({ signal }) => reuseSetupApi.policy(agencyId, companyId, signal), enabled: open, staleTime: 0, gcTime: 0, retry: 1 });
  return <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-base font-semibold text-slate-950">Returning traveller reuse</h2><p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">Set the documented purpose and privacy notice, then configure eligible collection groups. Individual consent and verification still apply.</p></div><Button type="button" variant="secondary" className="min-h-11" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "Close reuse settings" : "Configure reuse"}</Button></div>
    {open && <div className="mt-5 border-t border-slate-100 pt-5">{policy.isLoading ? <CompanyLoading /> : policy.isError || !policy.data ? <CompanyError message="Reuse settings could not be loaded." retry={() => void policy.refetch()} /> : <PolicyForm key={policy.data.revision} agencyId={agencyId} companyId={companyId} active={active} policy={policy.data} />}</div>}
  </section>;
}

function PolicyForm({ agencyId, companyId, policy, active }: { agencyId: string; companyId: string; policy: ReusePolicy; active: boolean }) {
  const [enabled, setEnabled] = useState(policy.enabled);
  const [purpose, setPurpose] = useState(policy.purpose_version ?? "");
  const [notice, setNotice] = useState(policy.notice_version ?? "");
  const [basis, setBasis] = useState(policy.processing_basis ?? "");
  const [saved, setSaved] = useState(false);
  const client = useQueryClient();
  const mutation = useMutation({ mutationFn: () => reuseSetupApi.savePolicy(agencyId, companyId, { expected_revision: policy.revision, enabled, retention_mode: "until_withdrawn", purpose_version: purpose.trim() || null, notice_version: notice.trim() || null, processing_basis: basis.trim() || null }), onSuccess: async () => { setSaved(true); await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); } });
  return <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (!mutation.isPending) mutation.mutate(); }}>
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={mutation.isPending || (!active && !enabled)} className="mt-1" />Enable returning traveller reuse for this company</label>
    {!active && <p className="text-sm text-amber-800">Activate the company before enabling reuse.</p>}
    <p className="rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-600">Retention: until the traveller withdraws reuse permission. Historical documents remain separate from the current passport used for future trips.</p>
    <fieldset disabled={mutation.isPending} className="grid gap-4 md:grid-cols-3"><Input label="Documented purpose version" required={enabled} maxLength={128} value={purpose} onChange={(event) => setPurpose(event.target.value)} hint="Reference your approved purpose document." /><Input label="Privacy notice version" required={enabled} maxLength={128} value={notice} onChange={(event) => setNotice(event.target.value)} hint="Reference the notice shown to travellers." /><Input label="Documented processing basis" required={enabled} maxLength={128} value={basis} onChange={(event) => setBasis(event.target.value)} hint="Enter the basis approved for your organisation." /></fieldset>
    {mutation.isError && <CompanyError message={companyErrorMessage(mutation.error, "Settings were not saved. Refresh the settings if another administrator changed them.")} />}
    {saved && <p role="status" className="text-sm text-emerald-700">Reuse settings saved.</p>}
    <Button type="submit" isLoading={mutation.isPending} disabled={enabled && (!active || !purpose.trim() || !notice.trim() || !basis.trim())}>Save reuse settings</Button>
  </form>;
}
