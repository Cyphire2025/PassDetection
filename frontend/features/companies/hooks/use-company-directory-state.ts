"use client";

import { useEffect, useState } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompanyPeople } from "./use-company-people";
import { useCompanyViewState } from "./use-company-view-state";
import type { CompanyPeopleSort, CompanySubmissionFilter } from "../types/company-people";
import { companySearchHint } from "../utils/company-search";

export function useCompanyDirectoryState(agencyId: string, companyId: string) {
  const view = useCompanyViewState();
  const search = view.params.get("peopleSearch") ?? "";
  const cursor = view.params.get("peopleCursor") ?? undefined;
  const selectedSort = view.params.get("peopleSort");
  const sort: CompanyPeopleSort = selectedSort === "name_asc" || selectedSort === "name_desc" ? selectedSort : "newest";
  const selectedCount = view.params.get("submissions");
  const submissions: CompanySubmissionFilter = selectedCount === "one" || selectedCount === "multiple" ? selectedCount : "all";
  const term = useDebounce(search.trim(), 250);
  const [reviewMatches, setReviewMatches] = useState(false);
  const settled = search.trim() === term;
  const searchHint = companySearchHint(search);
  const { people, scope, ready } = useCompanyPeople(agencyId, companyId, term, cursor, settled && !searchHint, reviewMatches, sort, submissions);
  const directoryChanged = (people.error as { code?: string } | null)?.code === "DIRECTORY_CHANGED";
  const update = view.update;
  useEffect(() => {
    if (cursor && directoryChanged) update({ peopleCursor: undefined });
  }, [cursor, directoryChanged, update]);
  return {
    view,
    search,
    cursor,
    sort,
    submissions,
    term,
    reviewMatches,
    setReviewMatches,
    settled,
    searchHint,
    people,
    scope,
    ready
  };
}

export type CompanyDirectoryState = ReturnType<typeof useCompanyDirectoryState>;
