"use client";

import { useId, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2 } from "lucide-react";
import { reuseSetupApi } from "../api/reuse-setup.api";
import { companyKeys, companyQueryOptions, useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading } from "./company-feedback";

/** Mounted only on Settings; group rows do not fetch configuration individually. */
export function CompanySettings({ agencyId, companyId, active }: { agencyId: string; companyId: string; active: boolean }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const key = [...scope, companyId, "reuse-policy"];
  const descriptionId = useId();
  const client = useQueryClient();
  const inFlight = useRef(false);
  const policy = useQuery({ queryKey: key, queryFn: ({ signal }) => reuseSetupApi.policy(agencyId, companyId, signal), enabled: ready, ...companyQueryOptions });
  const update = useMutation({
    mutationFn: (enabled: boolean) => {
      if (!ready || !policy.data) throw new Error("Company settings are unavailable.");
      return reuseSetupApi.savePolicy(agencyId, companyId, { expected_revision: policy.data.revision, enabled });
    },
    onSuccess: async (saved) => {
      await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId), refetchType: "none" });
      client.setQueryData(key, saved);
      await client.invalidateQueries({ queryKey: [...scope, companyId], exact: true });
    },
  });
  if (!ready || policy.isLoading) return <CompanyLoading />;
  if (policy.isError || !policy.data) return <CompanyError message="Settings could not be loaded." retry={() => void policy.refetch()} />;
  const enabled = policy.data.enabled;

  return <section aria-label="Company settings" className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
    <div className="flex items-start gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><FileCheck2 className="h-5 w-5" aria-hidden="true" /></span>
      <div className="min-w-0 flex-1"><h2 className="text-sm font-semibold text-slate-950">Use saved documents</h2><p id={descriptionId} className="mt-1 max-w-xl text-sm leading-6 text-slate-500">Applies to all groups for this company.</p></div>
      <button type="button" role="switch" aria-label="Use saved documents" aria-describedby={descriptionId} aria-checked={enabled} disabled={update.isPending || (!active && !enabled)}
        onClick={async () => {
          if (inFlight.current) return;
          inFlight.current = true;
          try { await update.mutateAsync(!enabled); } catch { /* Keep the saved value and show the error below. */ }
          finally { inFlight.current = false; }
        }} className="inline-flex h-11 w-14 shrink-0 items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:opacity-50"><span className={`inline-flex h-7 w-12 items-center rounded-full border-2 border-transparent transition-colors ${enabled ? "bg-blue-600" : "bg-slate-300"}`}><span className={`h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${enabled ? "translate-x-5" : "translate-x-0"}`} /></span></button>
    </div>
    <div role="status" className="ml-13 mt-2 text-xs text-slate-500">{update.isPending ? "Saving…" : update.isSuccess ? "Saved" : enabled ? "On" : "Off"}</div>
    {policy.data.notice_text && <details className="ml-13 mt-3 text-xs leading-5 text-slate-500"><summary className="w-fit cursor-pointer rounded font-medium text-slate-600 focus-visible:ring-2 focus-visible:ring-blue-600">How it works</summary><p className="mt-2 max-w-xl">{policy.data.notice_text}</p></details>}
    {!active && <p className="mt-3 text-sm text-amber-800">Activate this company to turn on saved documents.</p>}
    {update.isError && <div className="mt-4"><CompanyError message="This setting was not saved. Reload it and try again." retry={() => { update.reset(); void policy.refetch(); }} /></div>}
  </section>;
}
