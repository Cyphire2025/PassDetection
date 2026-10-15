"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { companyMatchingApi, type TravellerMatchCase } from "../api/company-matching.api";
import { companyKeys } from "../hooks/use-companies";
import { CompanyError, companyErrorMessage } from "./company-feedback";

export const PROFILE_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function CompanyMatchResolution({ agencyId, companyId, groupId, match, groupRevision, onPending, onBack, onRefresh }: {
  agencyId: string; companyId: string; groupId: string; match: TravellerMatchCase; groupRevision: number;
  onPending: (pending: boolean) => void; onBack: () => void; onRefresh: () => void;
}) {
  const client = useQueryClient();
  const [choice, setChoice] = useState<"proposed" | "known" | null>(null);
  const [knownId, setKnownId] = useState("");
  const [reason, setReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const selectedId = choice === "proposed" ? match.traveller_id ?? "" : choice === "known" ? knownId.trim() : "";
  const mutation = useMutation({
    mutationFn: () => companyMatchingApi.resolve(agencyId, companyId, groupId, match.id, { traveller_id: selectedId, expected_revision: match.revision, expected_group_revision: groupRevision, reason: reason.trim(), evidence_reviewed: true }),
    onMutate: () => onPending(true),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); },
    onSettled: () => onPending(false),
  });
  const blocked = mutation.isError && typeof mutation.error === "object" && mutation.error !== null && "status" in mutation.error && [403, 404, 409].includes(Number(mutation.error.status));
  const valid = PROFILE_ID_PATTERN.test(selectedId) && groupRevision >= 1 && acknowledged && reason.trim().length >= 10;
  if (mutation.isSuccess) return <div className="space-y-4 rounded-xl border border-blue-200 bg-blue-50 p-4"><div role="status" className="space-y-2 text-sm leading-6 text-blue-900"><p className="font-semibold">Roster decision saved</p><p>This decision records the reviewed association. It does not grant document access, record consent, merge people, or complete collection. The traveller must still pass the required verification and current trip checks.</p><p>Membership state: <span className="font-medium">{mutation.data.status}</span></p></div><Button type="button" variant="secondary" onClick={onBack}>Back to matching cases</Button></div>;
  return <form className="space-y-4 rounded-xl border border-blue-200 bg-blue-50/40 p-4" onSubmit={(event) => { event.preventDefault(); if (valid && !blocked && !mutation.isPending) mutation.mutate(); }}>
    <h3 className="text-base font-semibold text-slate-950">Review this association</h3>
    <p className="text-sm leading-6 text-slate-600">Inspect the source record and company traveller history. Select the exact person supported by that evidence. A proposed match has not established identity.</p>
    <fieldset disabled={mutation.isPending || blocked} className="space-y-3"><legend className="mb-2 text-sm font-medium text-slate-700">Select a traveller profile</legend>
      {match.traveller_id && <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm"><input type="radio" name="match-person" className="mt-1" checked={choice === "proposed"} onChange={() => { setChoice("proposed"); setAcknowledged(false); }} /><span className="min-w-0">Use the proposed traveller<span className="mt-1 block break-all text-xs text-slate-600">{match.traveller_id}</span></span></label>}
      <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm"><input type="radio" name="match-person" className="mt-1" checked={choice === "known"} onChange={() => { setChoice("known"); setAcknowledged(false); }} />Use an exact known traveller profile ID</label>
      {choice === "known" && <Input label="Known traveller profile ID" required value={knownId} maxLength={36} pattern={PROFILE_ID_PATTERN.source} onChange={(event) => { setKnownId(event.target.value); setAcknowledged(false); }} hint="Paste the existing UUID from a reviewed profile in this company. Do not enter a passport number, name or phone." />}
      <label className="block text-sm font-medium text-slate-700">Evidence and decision reason<textarea required minLength={10} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} className="mt-2 min-h-28 w-full rounded-lg border border-slate-300 bg-white p-3" /><span className="text-xs font-normal leading-5 text-slate-500">10–500 characters. Describe the evidence and decision; do not paste passport numbers, OTPs or document contents.</span></label>
      <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" required className="mt-1" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />I reviewed the source evidence and confirm that this exact traveller belongs on this group’s roster.</label>
    </fieldset>
    {mutation.isError && <CompanyError message={companyErrorMessage(mutation.error, "The association could not be saved. Your inputs are retained; retry or refresh this case.")} />}
    {blocked && <Button type="button" variant="secondary" onClick={onRefresh}>Refresh matching cases</Button>}
    <div className="flex flex-wrap justify-end gap-3"><Button type="button" variant="secondary" disabled={mutation.isPending} onClick={onBack}>Back to cases</Button><Button type="submit" className="h-auto min-h-11 whitespace-normal" disabled={!valid || blocked} isLoading={mutation.isPending}>Record roster decision</Button></div>
  </form>;
}
