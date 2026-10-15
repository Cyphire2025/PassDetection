"use client";

import { useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { formatPassportCountry } from "@/lib/utils/passport-country";
import { companyPassportsApi, type BlockedPassportStatus, type ManagedPassport } from "../api/company-passports.api";
import { companyKeys, useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, companyErrorMessage } from "./company-feedback";

export function CompanyPassports({ agencyId, companyId, travellerId, onClose }: { agencyId: string; companyId: string; travellerId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [selected, setSelected] = useState<ManagedPassport | null>(null);
  const [status, setStatus] = useState<BlockedPassportStatus>("lost");
  const [confirmed, setConfirmed] = useState(false);
  const passports = useQuery({ queryKey: [...scope, companyId, "travellers", travellerId, "passports"], queryFn: ({ signal }) => companyPassportsApi.list(agencyId, companyId, travellerId, signal), enabled: ready, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false });
  const mutation = useMutation({
    mutationFn: () => {
      if (!selected || !passports.data) throw new Error("Refresh and select a passport.");
      return companyPassportsApi.block(agencyId, companyId, travellerId, selected.id, status, passports.data.profile_revision, selected.revision);
    },
    onSuccess: async () => { setSelected(null); setConfirmed(false); await queryClient.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); },
  });
  const dialogRef = useRef<HTMLDivElement>(null);
  const title = useId();
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !mutation.isPending, onClose });
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"><section className="max-h-[90dvh] w-full max-w-lg space-y-4 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl">
    <div className="flex items-start justify-between gap-3"><h2 id={title} className="text-lg font-semibold text-slate-950">Manage traveller passports</h2><Button type="button" variant="ghost" onClick={onClose} disabled={mutation.isPending}>Close</Button></div>
    <p className="text-sm leading-6 text-slate-600">Mark a passport lost, cancelled or compromised to block future reuse. Previous trip documents are preserved.</p>
    {!ready || passports.isLoading ? <CompanyLoading /> : passports.isError ? <CompanyError message="Passport records could not be loaded." retry={() => void passports.refetch()} /> : <>
      <ul className="space-y-3">{passports.data?.items.map((passport) => <li key={passport.id} className="space-y-2 rounded-xl border border-slate-200 p-3"><p className="break-words text-sm font-semibold text-slate-900">{passport.passport_hint} · {formatPassportCountry(passport.issuing_country)}</p><p className="text-xs leading-5 text-slate-500">{passport.document_type} · {passport.status}{passport.is_default ? " · Usual passport" : ""}<br />Expires {passport.expiry_date ?? "date not available"}</p>{!["lost", "cancelled", "compromised"].includes(passport.status) && <Button type="button" variant="secondary" className="h-auto min-h-11 whitespace-normal" disabled={mutation.isPending} onClick={() => { setSelected(passport); setConfirmed(false); setStatus("lost"); mutation.reset(); }}>Change status for {passport.passport_hint}</Button>}</li>)}</ul>
      {!passports.data?.items.length && <p className="text-sm text-slate-500">No retained passport records are available.</p>}
      {passports.data?.limit_reached && <p className="text-sm text-amber-800">This view reached its record limit. Contact your administrator to review additional records.</p>}
      {selected && <form className="space-y-3 rounded-xl border border-red-200 bg-red-50 p-3" onSubmit={(event) => { event.preventDefault(); if (confirmed && !mutation.isPending) mutation.mutate(); }}>
        <h3 className="break-words text-sm font-semibold text-red-900">Block {selected.passport_hint}</h3>
        <label className="block text-sm font-medium text-red-900">New passport status<select value={status} disabled={mutation.isPending} onChange={(event) => { setStatus(event.target.value as BlockedPassportStatus); setConfirmed(false); }} className="mt-2 min-h-11 w-full rounded-lg border border-red-200 bg-white px-3"><option value="lost">Lost</option><option value="cancelled">Cancelled</option><option value="compromised">Compromised</option></select></label>
        <p className="text-sm leading-6 text-red-900">This prevents future use and revokes existing returning-traveller access grants. An older passport will not be selected automatically. Saved historical files are retained.</p>
        <label className="flex items-start gap-3 text-sm leading-6 text-red-900"><input type="checkbox" className="mt-1" checked={confirmed} disabled={mutation.isPending} onChange={(event) => setConfirmed(event.target.checked)} />I verified this passport’s status and understand that future reuse will be blocked.</label>
        <div className="flex flex-wrap justify-end gap-3"><Button type="button" variant="secondary" disabled={mutation.isPending} onClick={() => setSelected(null)}>Cancel</Button><Button type="submit" variant="danger" disabled={!confirmed} isLoading={mutation.isPending}>Confirm passport status</Button></div>
      </form>}
      {mutation.isError && <CompanyError message={companyErrorMessage(mutation.error, "The passport may have changed. Close this view and reload before trying again.")} />}
      {mutation.isSuccess && <p role="status" className="text-sm text-emerald-800">Passport status updated. Existing historical documents remain preserved.</p>}
    </>}
  </section></div>;
}
