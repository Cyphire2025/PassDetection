"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Images, RefreshCw } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { companyDataExportsApi, type CompanyDataExport, type CompanyExportKind } from "../api/company-data-exports.api";
import { useCompanyQueryContext } from "../hooks/use-companies";
import { CompanyError, CompanyLoading, CompanyPagination, companyErrorMessage } from "./company-feedback";

const RUNNING = new Set<CompanyDataExport["status"]>(["queued", "running"]);
const STATUS: Record<CompanyDataExport["status"], string> = { queued: "Queued", running: "Preparing", succeeded: "Ready", failed: "Failed", cancelled: "Cancelled", expired: "Expired" };

export function CompanyDataExports({ agencyId, companyId }: { agencyId: string; companyId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<string>();
  const keys = useRef<Partial<Record<CompanyExportKind, string>>>({});
  const inFlight = useRef(false);
  const prefix = [...scope, companyId, "data-exports"];
  const jobs = useQuery({ queryKey: [...prefix, cursor], queryFn: ({ signal }) => companyDataExportsApi.list(agencyId, companyId, cursor, signal), enabled: ready && open, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false, refetchInterval: (query) => open && query.state.status !== "error" && query.state.data?.items.some((job) => RUNNING.has(job.status)) ? 3000 : false, refetchIntervalInBackground: false });
  const create = useMutation({ mutationFn: (kind: CompanyExportKind) => {
    keys.current[kind] ??= crypto.randomUUID();
    return companyDataExportsApi.create(agencyId, companyId, kind, keys.current[kind]);
  }, onSuccess: async (job) => { delete keys.current[job.kind]; setOpen(true); setCursor(undefined); await client.invalidateQueries({ queryKey: prefix }); } });
  async function start(kind: CompanyExportKind) {
    if (!ready || inFlight.current) return;
    inFlight.current = true;
    try { await create.mutateAsync(kind); } catch { /* The same idempotency key is retained for a retry. */ }
    finally { inFlight.current = false; }
  }
  return <section aria-label="Company exports" className="space-y-3">
    <div className="flex flex-wrap gap-2"><Button type="button" variant="secondary" className="min-h-11" disabled={!ready || create.isPending} onClick={() => void start("excel")}><FileSpreadsheet className="h-4 w-4" aria-hidden="true" />Export Excel</Button><Button type="button" variant="secondary" className="min-h-11" disabled={!ready || create.isPending} onClick={() => void start("images")}><Images className="h-4 w-4" aria-hidden="true" />Export all images</Button><Button type="button" variant="ghost" className="min-h-11" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide exports" : "Recent exports"}</Button></div>
    {create.isError && <CompanyError message={companyErrorMessage(create.error, "The export could not be started. Try again.")} />}
    {open && <div className="overflow-hidden rounded-xl border border-slate-200 bg-white"><div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2"><p className="text-xs leading-5 text-slate-500">Excel contains one current row per person. Images include all saved versions.</p><Button type="button" size="icon" variant="ghost" aria-label="Refresh exports" disabled={!ready || jobs.isFetching} onClick={() => void jobs.refetch()}><RefreshCw className="h-4 w-4" aria-hidden="true" /></Button></div>
      {!ready || jobs.isLoading ? <CompanyLoading /> : jobs.isError ? <CompanyError message="Exports could not be loaded." retry={() => void jobs.refetch()} /> : <><ul className="divide-y divide-slate-100">{jobs.data?.items.map((job) => <li key={job.id} className="space-y-3 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-medium text-slate-900">{job.kind === "excel" ? "People · Excel" : "All document images · ZIP"}</p><p role={RUNNING.has(job.status) ? "status" : undefined} className="mt-1 text-xs text-slate-500">{STATUS[job.status]} · {job.processed_count.toLocaleString()} records · {new Date(job.created_at).toLocaleDateString()}</p></div>{job.status === "succeeded" && <Button type="button" variant="secondary" size="sm" className="min-h-11" aria-expanded={selected === job.id} onClick={() => setSelected(selected === job.id ? undefined : job.id)}>{selected === job.id ? "Hide files" : "View files"}</Button>}</div>{job.status === "failed" && <p className="text-xs text-red-700">This export did not finish. Start a new export to try again.</p>}{selected === job.id && job.status === "succeeded" && <ExportFiles agencyId={agencyId} companyId={companyId} jobId={job.id} />}</li>)}</ul>{!jobs.data?.items.length && <p className="p-4 text-sm text-slate-500">No recent exports.</p>}{(cursor || jobs.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={jobs.data?.has_more ?? false} nextCursor={jobs.data?.next_cursor ?? null} pending={jobs.isFetching} onChange={(value) => { setCursor(value); setSelected(undefined); }} />}</>}
    </div>}
  </section>;
}

function ExportFiles({ agencyId, companyId, jobId }: { agencyId: string; companyId: string; jobId: string }) {
  const { scope, ready } = useCompanyQueryContext(agencyId);
  const [cursor, setCursor] = useState<string>();
  const parts = useQuery({ queryKey: [...scope, companyId, "data-exports", jobId, "parts", cursor], queryFn: ({ signal }) => companyDataExportsApi.parts(agencyId, companyId, jobId, cursor, signal), enabled: ready, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false });
  if (!ready || parts.isLoading) return <CompanyLoading />;
  if (parts.isError) return <CompanyError message="Export files could not be loaded." retry={() => void parts.refetch()} />;
  return <div className="space-y-3 rounded-lg bg-slate-50 p-3"><ul className="space-y-2">{parts.data?.items.map((part) => <li key={part.id}><a href={companyDataExportsApi.downloadUrl(agencyId, companyId, jobId, part.id)} download={part.filename} className={buttonVariants({ variant: "secondary", size: "sm", className: "h-auto min-h-11 max-w-full whitespace-normal text-left" })}><Download className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="min-w-0 break-all">{part.filename} · {(part.byte_size / 1024 / 1024).toFixed(1)} MB</span></a></li>)}</ul><a href={companyDataExportsApi.manifestUrl(agencyId, companyId, jobId)} download className="inline-flex min-h-11 items-center rounded text-xs font-medium text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600">Download file list</a>{(cursor || parts.data?.has_more) && <CompanyPagination cursor={cursor} hasMore={parts.data?.has_more ?? false} nextCursor={parts.data?.next_cursor ?? null} pending={parts.isFetching} onChange={setCursor} />}</div>;
}
