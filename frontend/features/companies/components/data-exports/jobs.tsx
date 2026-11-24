import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CompanyDataExportsController } from "../../hooks/use-company-data-exports";
import { COMPANY_EXPORT_STATUS, companyExportRunning } from "../../utils/company-export-status";
import { CompanyError, CompanyLoading, CompanyPagination } from "../company-feedback";
import { CompanyExportFiles } from "./files";

export function CompanyExportJobs({ agencyId, companyId, controller }: {
  agencyId: string; companyId: string; controller: CompanyDataExportsController;
}) {
  const { ready, jobs, cursor, selected, setSelected, changePage } = controller;
  return <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2">
      <p className="text-xs leading-5 text-slate-500">Excel contains one current row per person. Images include all saved versions.</p>
      <Button type="button" size="icon" variant="ghost" aria-label="Refresh exports" disabled={!ready || jobs.isFetching}
        onClick={() => void jobs.refetch()}><RefreshCw className="h-4 w-4" aria-hidden="true" /></Button>
    </div>
    {!ready || jobs.isLoading ? <CompanyLoading /> : jobs.isError
      ? <CompanyError message="Exports could not be loaded." retry={() => void jobs.refetch()} /> : <>
        <ul className="divide-y divide-slate-100">
          {jobs.data?.items.map((job) => <li key={job.id} className="space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-slate-900">{job.kind === "excel" ? "People · Excel" : "All document images · ZIP"}</p>
                <p role={companyExportRunning(job.status) ? "status" : undefined} className="mt-1 text-xs text-slate-500">
                  {COMPANY_EXPORT_STATUS[job.status]} · {job.processed_count.toLocaleString()} records · {new Date(job.created_at).toLocaleDateString()}
                </p>
              </div>
              {job.status === "succeeded" && <Button type="button" variant="secondary" size="sm" className="min-h-11"
                aria-expanded={selected === job.id} onClick={() => setSelected(selected === job.id ? undefined : job.id)}>
                {selected === job.id ? "Hide files" : "View files"}
              </Button>}
            </div>
            {job.status === "failed" && <p className="text-xs text-red-700">This export did not finish. Start a new export to try again.</p>}
            {selected === job.id && job.status === "succeeded" && <CompanyExportFiles agencyId={agencyId} companyId={companyId} jobId={job.id} />}
          </li>)}
        </ul>
        {!jobs.data?.items.length && <p className="p-4 text-sm text-slate-500">No recent exports.</p>}
        {(cursor || jobs.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={jobs.data?.has_more ?? false}
          nextCursor={jobs.data?.next_cursor ?? null} pending={jobs.isFetching} onChange={changePage} />}
      </>}
  </div>;
}
