"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompanyPeople } from "../hooks/use-company-people";
import { useCompanyViewState } from "../hooks/use-company-view-state";
import { CompanyPagination } from "./company-feedback";
import { CompanyDataExports } from "./company-data-exports";
import { CompanyPeopleToolbar } from "./company-people-toolbar";
import { CompanyPeopleResults } from "./company-people-results";
import { companySearchHint } from "../utils/company-search";

const CompanyMatchQueue = dynamic(() => import("./company-match-queue").then((module) => module.CompanyMatchQueue));

/** One indexed 100-person page; private fields and images load on explicit open. */
export function CompanyAllData({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const view = useCompanyViewState();
  const search = view.params.get("peopleSearch") ?? "";
  const cursor = view.params.get("peopleCursor") ?? undefined;
  const selectedSort = view.params.get("peopleSort");
  const sort = selectedSort === "name_asc" || selectedSort === "name_desc" ? selectedSort : "newest";
  const selectedCount = view.params.get("submissions");
  const submissions = selectedCount === "one" || selectedCount === "multiple" ? selectedCount : "all";
  const term = useDebounce(search.trim(), 250);
  const [reviewMatches, setReviewMatches] = useState(false);
  const settled = search.trim() === term;
  const searchHint = companySearchHint(search);
  const { people, scope, ready } = useCompanyPeople(agencyId, companyId, term, cursor, settled && !searchHint, reviewMatches, sort, submissions);
  const directoryChanged = (people.error as { code?: string } | null)?.code === "DIRECTORY_CHANGED";
  const update = view.update;
  useEffect(() => { if (cursor && directoryChanged) update({ peopleCursor: undefined }); }, [cursor, directoryChanged, update]);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><CompanyDataExports agencyId={agencyId} companyId={companyId} /><Button type="button" variant="ghost" disabled={!ready || people.isError} onClick={() => setReviewMatches(true)}>Review matches</Button></div>
    <section aria-label="Company people" aria-busy={!settled || people.isFetching} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <CompanyPeopleToolbar search={search} sort={sort} submissions={submissions} pending={people.isFetching} disabled={!ready || people.isFetching || Boolean(searchHint)} onSearch={(value) => view.update({ peopleSearch: value, peopleCursor: undefined })} onSort={(value) => view.update({ peopleSort: value, peopleCursor: undefined })} onSubmissions={(value) => view.update({ submissions: value, peopleCursor: undefined })} refresh={() => void people.refetch()} />
      <CompanyPeopleResults data={people.data} loading={!ready || people.isLoading} error={people.isError} retry={() => void people.refetch()} companyId={companyId} query={view.query} search={term} hint={searchHint} />
      <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">Up to 100 people per page</div>
      {(cursor || people.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={!people.isError && Boolean(people.data?.has_more)} nextCursor={people.data?.next_cursor ?? null} pending={!ready || !settled || people.isFetching} onChange={(value) => view.update({ peopleCursor: value })} />}
    </section>
    {ready && !people.isError && reviewMatches && <CompanyMatchQueue key={scope.join(":")} agencyId={agencyId} companyId={companyId} onClose={() => setReviewMatches(false)} />}
  </div>;
}
