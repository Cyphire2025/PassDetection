"use client";

import { usePrivateMutation } from "@/hooks/use-private-mutation";

import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { companyDataExportsApi, type CompanyExportKind } from "../api/company-data-exports.api";
import { useCompanyQueryContext } from "./use-companies";
import { companyExportRunning } from "../utils/company-export-status";

export function useCompanyDataExports(agencyId: string, companyId: string) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const keys = useRef<Partial<Record<CompanyExportKind, string>>>({});
  const inFlight = useRef(false);
  const prefix = [...scope, companyId, "data-exports"];

  const jobs = useQuery({
    queryKey: [...prefix, cursor],
    queryFn: ({ signal }) => companyDataExportsApi.list(agencyId, companyId, cursor, signal),
    enabled: ready && open,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => open && query.state.status !== "error"
      && query.state.data?.items.some((job) => companyExportRunning(job.status)) ? 3000 : false,
    refetchIntervalInBackground: false,
  });
  const create = usePrivateMutation({
    mutationFn: (kind: CompanyExportKind, _context, owner) => {
      keys.current[kind] ??= crypto.randomUUID();
      return companyDataExportsApi.create(agencyId, companyId, kind, keys.current[kind], owner.requestConfig);
    },
    onSuccess: async (job) => {
      delete keys.current[job.kind];
      setOpen(true);
      setCursor(undefined);
      await client.invalidateQueries({ queryKey: prefix });
    },
  });

  async function start(kind: CompanyExportKind) {
    if (!ready || inFlight.current) return;
    inFlight.current = true;
    try {
      await create.mutateAsync(kind);
    } catch {
      // The same idempotency key is retained for a retry.
    } finally {
      inFlight.current = false;
    }
  }

  function changePage(value: string | undefined) {
    setCursor(value);
    setSelected(undefined);
  }
  return { ready, open, setOpen, cursor, selected, setSelected, jobs, create, start, changePage };
}

export type CompanyDataExportsController = ReturnType<typeof useCompanyDataExports>;
