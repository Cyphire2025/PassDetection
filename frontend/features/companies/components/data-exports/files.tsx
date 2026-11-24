"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { companyDataExportsApi } from "../../api/company-data-exports.api";
import { useCompanyQueryContext } from "../../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination } from "../company-feedback";

export function CompanyExportFiles({ agencyId, companyId, jobId }: { agencyId: string; companyId: string; jobId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [cursor, setCursor] = useState<string>();
  const parts = useQuery({
    queryKey: [...scope, companyId, "data-exports", jobId, "parts", cursor],
    queryFn: ({ signal }) => companyDataExportsApi.parts(agencyId, companyId, jobId, cursor, signal),
    enabled: ready,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  if (!ready || parts.isLoading) return <CompanyLoading />;
  if (parts.isError) return <CompanyError message="Export files could not be loaded." retry={() => void parts.refetch()} />;
  return <div className="space-y-3 rounded-lg bg-slate-50 p-3">
    <ul className="space-y-2">
      {parts.data?.items.map((part) => <li key={part.id}>
        <a href={companyDataExportsApi.downloadUrl(agencyId, companyId, jobId, part.id)} download={part.filename}
          className={buttonVariants({ variant: "secondary", size: "sm", className: "h-auto min-h-11 max-w-full whitespace-normal text-left" })}>
          <Download className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-all">{part.filename} · {(part.byte_size / 1024 / 1024).toFixed(1)} MB</span>
        </a>
      </li>)}
    </ul>
    <a href={companyDataExportsApi.manifestUrl(agencyId, companyId, jobId)} download
      className="inline-flex min-h-11 items-center rounded text-xs font-medium text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600">
      Download file list
    </a>
    {(cursor || parts.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={parts.data?.has_more ?? false}
      nextCursor={parts.data?.next_cursor ?? null} pending={parts.isFetching} onChange={setCursor} />}
  </div>;
}
