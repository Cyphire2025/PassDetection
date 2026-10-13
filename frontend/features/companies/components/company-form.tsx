"use client";

import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { useCompanyMutations } from "../hooks/use-companies";
import type { Company } from "../types";
import { CompanyError, companyErrorMessage } from "./company-feedback";

export function CompanyForm({ agencyId, company, onClose }: { agencyId: string; company: Company | null; onClose: () => void }) {
  const [name, setName] = useState(company?.name ?? "");
  const [reference, setReference] = useState(company?.external_reference ?? "");
  const [error, setError] = useState<string>();
  const mutations = useCompanyMutations(agencyId);
  const pending = mutations.create.isPending || mutations.update.isPending;
  const inFlight = useRef(false);
  const title = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });

  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={handleKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
    <form className="max-h-[90dvh] w-full max-w-lg space-y-5 overflow-y-auto rounded-2xl bg-white p-5 shadow-xl" onSubmit={async (event) => {
      event.preventDefault();
      if (inFlight.current || !name.trim()) return;
      inFlight.current = true;
      setError(undefined);
      try {
        const input = { name: name.trim(), external_reference: reference.trim() || null };
        if (company) await mutations.update.mutateAsync({ id: company.id, expected_revision: company.revision, ...input });
        else await mutations.create.mutateAsync(input);
        onClose();
      } catch (cause) { setError(companyErrorMessage(cause, "The company could not be saved. Your changes are still here; retry when ready.")); }
      finally { inFlight.current = false; }
    }}>
      <div><h2 id={title} className="text-lg font-semibold text-slate-950">{company ? "Edit company / client" : "Create company / client"}</h2><p className="mt-1 text-sm text-slate-500">Keep company details consistent across groups and GC App.</p></div>
      <Input label="Company name" required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} disabled={pending} data-dialog-initial-focus />
      <Input label="External reference (optional)" maxLength={128} value={reference} onChange={(event) => setReference(event.target.value)} disabled={pending} hint="Your internal client reference. Leading zeros are preserved." />
      {error && <CompanyError message={error} />}
      <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 pt-4"><Button variant="secondary" type="button" disabled={pending} onClick={onClose}>Cancel</Button><Button type="submit" disabled={!name.trim()} isLoading={pending}>{company ? "Save changes" : "Create company"}</Button></div>
    </form>
  </div>;
}
