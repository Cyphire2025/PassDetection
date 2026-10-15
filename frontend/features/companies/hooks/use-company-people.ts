"use client";

import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { companyPeopleApi } from "../api/company-people.api";
import { companyQueryOptions, useCompanyQueryContext } from "./use-companies";
import type { CompanyPeopleSort, CompanySubmissionFilter } from "../types/company-people";
import { companyIndexPending } from "../utils/company-index-status";

/** Check one visible first page at most 12 times (~2 minutes), without blanking it. */
export function useCompanyPeople(agencyId: string, companyId: string, search: string,
  cursor: string | undefined, settled: boolean, pauseRefresh: boolean,
  sort: CompanyPeopleSort = "newest", submissions: CompanySubmissionFilter = "all") {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const people = useQuery({
    queryKey: [...scope, companyId, "people", "directory", { search, cursor, sort, submissions }],
    queryFn: ({ signal }) => companyPeopleApi.list(agencyId, companyId, { search, cursor, sort, submissions }, signal),
    enabled: ready && settled,
    ...companyQueryOptions,
    refetchIntervalInBackground: false,
    refetchInterval: (query) => !pauseRefresh && !search && !cursor
      && query.state.status === "success" && companyIndexPending(query.state.data)
      && query.state.dataUpdateCount <= 12
      ? query.state.dataUpdateCount <= 6 ? 5_000 : 15_000 : false,
  });
  const hasData = ready && !people.isError && Boolean(people.data);
  const pending = people.data?.indexing_pending;
  const progress = people.data?.items.map((person) => [person.id, person.revision,
    person.trip_count, person.submission_count, person.document_version_count].join(":")).join("|");
  const observed = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!hasData || search || cursor) return;
    const next = `${pending}:${progress}`;
    if (observed.current !== undefined && observed.current !== next) void client.invalidateQueries({ queryKey: [...scope, companyId, "summary"], exact: true });
    observed.current = next;
  }, [client, hasData, pending, progress, scope, companyId, search, cursor]);
  return { people, scope, ready };
}
