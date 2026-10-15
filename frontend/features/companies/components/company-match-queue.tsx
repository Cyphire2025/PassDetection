"use client";

import { useId, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompanyGroups, useCompanyQueryContext } from "../hooks/use-companies";
import type { CompanyGroup } from "../types";
import { CompanyError, CompanyLoading, CompanyPagination } from "./company-feedback";

const CompanyMatchingDialog = dynamic(() => import("./company-matching-dialog").then((module) => module.CompanyMatchingDialog), { loading: () => <CompanyLoading /> });

export function CompanyMatchQueue({ agencyId, companyId, onClose }: { agencyId: string; companyId: string; onClose: () => void }) {
  const { ready, scope } = useCompanyQueryContext(agencyId);
  const [search, setSearch] = useState("");
  const term = useDebounce(search.trim(), 250);
  const [cursor, setCursor] = useState<string>();
  const [group, setGroup] = useState<CompanyGroup>();
  const title = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: !group, canClose: true, onClose });
  const groups = useCompanyGroups(agencyId, companyId, { search: term, cursor, page_size: 25, phase: "all" });
  const loading = !ready || groups.isLoading || search.trim() !== term;
  if (ready && !groups.isError && group) return <CompanyMatchingDialog key={`${scope.join(":")}:${group.id}`} agencyId={agencyId} companyId={companyId} group={group} onClose={() => setGroup(undefined)} />;
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-3"><section className="max-h-[90dvh] w-full max-w-xl space-y-4 overflow-y-auto rounded-2xl bg-white p-4 shadow-xl sm:p-5">
    <header className="flex items-center justify-between gap-3"><h2 id={title} className="text-lg font-semibold text-slate-950">Review matches</h2><Button type="button" variant="ghost" onClick={onClose}>Close</Button></header>
    <Input label="Search groups to review" value={search} onChange={(event) => { setSearch(event.target.value); setCursor(undefined); }} placeholder="Search groups" />
    {loading ? <CompanyLoading /> : groups.isError ? <CompanyError message="Groups could not be loaded." retry={() => void groups.refetch()} /> : <><ul className="divide-y divide-slate-100">{groups.data?.items.map((item) => <li key={item.id} className="flex items-center gap-3 py-3"><span className="min-w-0 flex-1 break-words text-sm font-medium text-slate-900">{item.name}</span><Button type="button" variant="secondary" className="min-h-11" aria-label={`Review matches for ${item.name}`} onClick={() => setGroup(item)}>Review</Button></li>)}</ul>{!groups.data?.items.length && <p className="text-sm text-slate-500">No groups found.</p>}{Boolean(cursor || groups.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={groups.data?.has_more ?? false} nextCursor={groups.data?.next_cursor ?? null} pending={groups.isFetching} onChange={setCursor} />}</>}
  </section></div>;
}
