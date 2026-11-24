"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { companyPeopleApi } from "../api/company-people.api";
import { companyKeys, useCompanyQueryContext } from "./company-query-state";
import { useCompanyViewState } from "./use-company-view-state";
import { useCompanyAgency } from "../components/company-agency-scope";

export function useCompanyPersonPage(companyId: string, personId: string) {
  const agencyId = useCompanyAgency();
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const view = useCompanyViewState();
  const [managePassports, setManagePassports] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const record = useQuery({
    queryKey: [...scope, companyId, "people", personId, "record"],
    queryFn: ({ signal }) => companyPeopleApi.record(agencyId, companyId, personId, signal),
    enabled: ready,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false
  });
  const onSaved = async () => {
    setEditing(false);
    setSaved(true);
    await client.invalidateQueries({ queryKey: companyKeys.scope(agencyId) });
  };
  const data = ready && !record.isError ? record.data : undefined;
  const back = new URLSearchParams(view.query);
  back.delete("personTab");
  back.set("tab", "data");
  return {
    agencyId,
    ready,
    view,
    managePassports,
    setManagePassports,
    editing,
    setEditing,
    busy,
    setBusy,
    saved,
    setSaved,
    record,
    onSaved,
    data,
    back
  };
}
