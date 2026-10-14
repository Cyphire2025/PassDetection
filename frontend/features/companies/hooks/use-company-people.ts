"use client";

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { companyPeopleApi } from "../api/company-people.api";
import { useCompanyQueryContext } from "./use-companies";

/** Check one visible first page at most 12 times (~2 minutes), without blanking it. */
export function useCompanyPeople(agencyId: string, companyId: string, search: string,
  cursor: string | undefined, settled: boolean, pauseRefresh: boolean) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const people = useQuery({
    queryKey: [...scope, companyId, "people", search, cursor],
    queryFn: ({ signal }) => companyPeopleApi.list(agencyId, companyId, { search, cursor }, signal),
    enabled: ready && settled,
    staleTime: 0, gcTime: 0, refetchOnWindowFocus: false, retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: (query) => !pauseRefresh && !search && !cursor
      && query.state.status === "success" && query.state.data?.indexing_pending
      && query.state.dataUpdateCount <= 12
      ? query.state.dataUpdateCount <= 6 ? 5_000 : 15_000 : false,
  });
  const hasData = ready && !people.isError && Boolean(people.data);
  const pending = people.data?.indexing_pending;
  const progress = people.data?.items.map((person) => [person.id, person.revision,
    person.trip_count, person.document_version_count].join(":")).join("|");
  useEffect(() => {
    if (hasData) void client.invalidateQueries({ queryKey: [...scope, companyId, "summary"], exact: true });
  }, [client, hasData, pending, progress, scope, companyId]);
  return { people, scope, ready };
}
