"use client";

import { useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { reuseSetupApi } from "../api/reuse-setup.api";
import { travellerEnrollmentApi, type EnrollmentSource } from "../api/traveller-enrollment.api";
import { companyKeys } from "../hooks/use-companies";
import type { CompanyGroup } from "../types";
import { CompanyError, CompanyLoading, CompanyPagination, companyErrorMessage } from "./company-feedback";
import { EnrollmentDocumentContext } from "./enrollment-document-context";

export function TravellerEnrollmentDialog({ agencyId, companyId, group, onClose }: { agencyId: string; companyId: string; group: CompanyGroup; onClose: () => void }) {
  const [pending, setPending] = useState(false);
  const title = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !pending, onClose });
  const policy = useQuery({ queryKey: [...companyKeys.scope(agencyId), companyId, "reuse-policy"], queryFn: ({ signal }) => reuseSetupApi.policy(agencyId, companyId, signal), staleTime: 0, gcTime: 0, retry: 1 });
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-3 sm:p-5"><section className="max-h-[90dvh] w-full max-w-xl space-y-4 overflow-y-auto rounded-2xl bg-white p-4 shadow-xl sm:p-5"><div className="flex items-start justify-between gap-3"><div><h2 id={title} className="text-lg font-semibold text-slate-950">Enable a traveller’s future reuse</h2><p className="mt-1 break-words text-sm text-slate-500">{group.name}</p></div><Button type="button" variant="ghost" onClick={onClose} disabled={pending}>Close</Button></div>
    {policy.isLoading ? <CompanyLoading /> : policy.isError ? <CompanyError message="Company reuse policy could not be checked." retry={() => void policy.refetch()} /> : !policy.data?.enabled ? <p role="status" className="rounded-xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">Configure and enable the company’s returning traveller policy before enrolling retained documents. The record still remains available for this trip.</p> : <EnrollmentForm agencyId={agencyId} companyId={companyId} group={group} onPending={setPending} />}
  </section></div>;
}

function EnrollmentForm({ agencyId, companyId, group, onPending }: { agencyId: string; companyId: string; group: CompanyGroup; onPending: (value: boolean) => void }) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 250);
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<(EnrollmentSource & { groupRevision: number }) | null>(null);
  const [evidence, setEvidence] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [issuer, setIssuer] = useState("");
  const [documentType, setDocumentType] = useState("");
  const [sourceOpened, setSourceOpened] = useState(false);
  const [contextConfirmed, setContextConfirmed] = useState(false);
  const [associationConfirmed, setAssociationConfirmed] = useState(false);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const client = useQueryClient();
  const sources = useQuery({ queryKey: [...companyKeys.scope(agencyId), companyId, group.id, "enrollment-sources", debounced, cursor], queryFn: ({ signal }) => travellerEnrollmentApi.sources(agencyId, companyId, group.id, debounced, cursor, signal), enabled: !debounced.trim() || debounced.trim().length >= 3, staleTime: 0, gcTime: 0, retry: 1 });
  const mutation = useMutation({ mutationFn: () => { if (!selected) throw new Error("Select an accepted saved submission."); return travellerEnrollmentApi.enroll(agencyId, companyId, group.id, { source_submission_id: selected.id, expected_extraction_revision: selected.extraction_revision, expected_group_revision: selected.groupRevision, permission_evidence_reference: evidence.trim(), idempotency_key: requestKey, change_kind: selected.candidate_change_kind ?? "initial", candidate_association_confirmed: selected.candidate_traveller_id ? associationConfirmed : false, reviewed_issuing_country: issuer, reviewed_document_type: documentType.trim(), reviewed_context_confirmed: true }); }, onMutate: () => onPending(true), onSuccess: async () => { await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) }); }, onSettled: () => onPending(false) });
  if (mutation.data) return <div role="status" className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-900"><p>Traveller enrollment accepted.</p><p>{mutation.data.copies_pending ? `${mutation.data.copies_pending} protected document copies are pending background processing. Historical document access stays unavailable until processing finishes.` : "The accepted document revision is recorded for future reuse, subject to verification and trip suitability."}</p></div>;
  return <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (selected && confirmed && contextConfirmed && (!selected.candidate_traveller_id || associationConfirmed) && !mutation.isPending) mutation.mutate(); }}>
    <p className="text-sm leading-6 text-slate-600">Choose an already reviewed submission and reference actual recorded permission for future reuse. This action does not infer consent from a phone number or AI extraction.</p>
    <Input label="Search accepted submissions" value={search} maxLength={120} onChange={(event) => { setSearch(event.target.value); setCursor(undefined); }} disabled={mutation.isPending} />
    {search.trim().length > 0 && search.trim().length < 3 ? <p className="text-sm text-slate-500">Enter at least three characters to search.</p> : sources.isLoading || search !== debounced ? <CompanyLoading /> : sources.isError ? <CompanyError message="Accepted submissions could not be loaded." retry={() => void sources.refetch()} /> : <fieldset disabled={mutation.isPending}><legend className="mb-2 text-sm font-medium text-slate-700">Saved submission</legend><ul className="max-h-56 space-y-2 overflow-y-auto">{sources.data?.items.map((source) => <li key={source.id}><label className="flex items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm"><input type="radio" name="enrollment-source" checked={selected?.id === source.id} onChange={() => { setSelected({ ...source, groupRevision: sources.data!.expected_group_revision }); setRequestKey(crypto.randomUUID()); setConfirmed(false); setContextConfirmed(false); setAssociationConfirmed(false); setSourceOpened(false); setIssuer(""); setDocumentType(""); mutation.reset(); }} className="mt-1" /><span className="min-w-0 break-words"><span className="font-medium text-slate-900">{source.display_name}</span><span className="block text-xs text-slate-500">{source.status === "staff_approved" ? "Staff approved" : "Confirmed"} · extraction revision {source.extraction_revision}</span></span></label></li>)}</ul>{!sources.data?.items.length && <p className="text-sm text-slate-500">No accepted submissions match this search. Review and approve the saved passport first.</p>}</fieldset>}
    <CompanyPagination cursor={cursor} hasMore={Boolean(sources.data?.next_cursor)} nextCursor={sources.data?.next_cursor ?? null} pending={sources.isFetching || search !== debounced || mutation.isPending} onChange={setCursor} />
    {selected && <p className="rounded-xl bg-blue-50 p-3 text-sm text-blue-900">Selected: {selected.display_name}. <Link className="font-medium underline" target="_blank" rel="noopener noreferrer" onClick={() => setSourceOpened(true)} href={ROUTES.dashboard.passportDetail(selected.id)}>Review this saved submission</Link></p>}
    <EnrollmentDocumentContext issuer={issuer} documentType={documentType} confirmed={contextConfirmed} sourceOpened={sourceOpened} disabled={mutation.isPending} onIssuer={setIssuer} onType={setDocumentType} onConfirmed={setContextConfirmed} />
    {selected?.candidate_traveller_id && <label className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900"><input type="checkbox" required checked={associationConfirmed} onChange={(event) => setAssociationConfirmed(event.target.checked)} disabled={mutation.isPending} className="mt-1" />Accept this {selected.candidate_change_kind ?? "document"} update for the previously verified traveller{selected.candidate_display_name ? `: ${selected.candidate_display_name}` : ""}. I reviewed the identity association and the accepted new document.</label>}
    <Input label="Recorded permission evidence reference" value={evidence} required minLength={3} maxLength={500} onChange={(event) => setEvidence(event.target.value)} disabled={mutation.isPending} hint="Reference the recorded permission or approved evidence. Do not enter passport numbers or invent a consent statement." />
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" required checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} disabled={mutation.isPending} className="mt-1" />I checked the accepted document and recorded evidence authorising this traveller’s future reuse.</label>
    {mutation.isError && <CompanyError message={companyErrorMessage(mutation.error, "Enrollment was not confirmed. Your evidence reference remains here; refresh if the submission or group changed.")} />}
    <Button type="submit" className="h-auto min-h-11 whitespace-normal" isLoading={mutation.isPending} disabled={!selected || !confirmed || !contextConfirmed || Boolean(selected?.candidate_traveller_id && !associationConfirmed) || evidence.trim().length < 3}>Enroll accepted traveller</Button>
  </form>;
}
