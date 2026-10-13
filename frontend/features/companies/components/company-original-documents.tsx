"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { companyPeopleApi } from "../api/company-people.api";
import { useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";
import { CompanyDocumentPreview } from "./company-document-preview";

export function CompanyOriginalDocuments({ agencyId, companyId, personId }: { agencyId: string; companyId: string; personId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const [preview, setPreview] = useState<{ kind: "source"; sourceId: string; side: string }>();
  const sources = useQuery({ queryKey: [...scope, companyId, "people", personId, "sources", cursor], queryFn: ({ signal }) => companyPeopleApi.sources(agencyId, companyId, personId, cursor, signal), enabled: ready && open, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false });
  return <section className="border-t border-slate-100 pt-4"><Button type="button" variant="ghost" aria-expanded={open} onClick={() => { setOpen(!open); setPreview(undefined); }}>Original trip documents</Button>
    {open && (!ready || sources.isLoading ? <CompanyLoading /> : sources.isError ? <CompanyError message="Original documents could not be loaded." retry={() => void sources.refetch()} /> : <div className="mt-3 space-y-3"><ul className="space-y-3">{sources.data?.items.map((source) => <li key={source.id} className="rounded-xl border border-slate-200 p-3"><h3 className="break-words text-sm font-medium text-slate-900">{source.group_name}</h3><p className="mt-1 text-xs text-slate-500">{new Date(source.created_at).toLocaleDateString()}</p><div className="mt-3 flex flex-wrap gap-2">{source.available_sides.map((side) => <Button key={side} type="button" size="sm" variant="secondary" className="min-h-11" aria-label={`View original ${side.replaceAll("_", " ")} from ${source.group_name}`} onClick={() => setPreview({ kind: "source", sourceId: source.id, side })}>{side.replaceAll("_", " ")}</Button>)}</div>{!source.available_sides.length && <p className="mt-2 text-xs text-slate-500">No available images.</p>}</li>)}</ul>{!sources.data?.items.length && <p className="text-sm text-slate-500">No original trip documents.</p>}{Boolean(cursor || sources.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={sources.data?.has_more ?? false} nextCursor={sources.data?.next_cursor ?? null} pending={sources.isFetching} onChange={(value) => { setCursor(value); setPreview(undefined); }} />}{preview && <CompanyDocumentPreview key={`${preview.sourceId}:${preview.side}`} agencyId={agencyId} companyId={companyId} personId={personId} document={preview} onClose={() => setPreview(undefined)} />}</div>)}
  </section>;
}
