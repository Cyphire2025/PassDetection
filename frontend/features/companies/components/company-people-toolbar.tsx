import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceToolbar } from "@/components/shared/workspace-ui";
import type { CompanyPeopleSort, CompanySubmissionFilter } from "../types/company-people";

export function CompanyPeopleToolbar({ search, sort, submissions, pending, disabled, onSearch, onSort, onSubmissions, refresh }: {
  search: string; sort: CompanyPeopleSort; submissions: CompanySubmissionFilter; pending: boolean; disabled: boolean;
  onSearch: (value: string) => void; onSort: (value: CompanyPeopleSort) => void;
  onSubmissions: (value: CompanySubmissionFilter) => void; refresh: () => void;
}) {
  const selectClass = "min-h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 sm:w-auto";
  return <WorkspaceToolbar query={search} onQueryChange={onSearch} searchLabel="Search company people" placeholder="Search a name or traveller ID">
    <label className="min-w-0"><span className="sr-only">Sort people</span><select className={selectClass} value={sort} onChange={(event) => onSort(event.target.value as CompanyPeopleSort)}><option value="newest">Latest submissions</option><option value="name_asc">Name · A–Z</option><option value="name_desc">Name · Z–A</option></select></label>
    <label className="min-w-0"><span className="sr-only">Number of submissions</span><select className={selectClass} value={submissions} onChange={(event) => onSubmissions(event.target.value as CompanySubmissionFilter)}><option value="all">All submissions</option><option value="one">One submission</option><option value="multiple">Multiple submissions</option></select></label>
    <Button type="button" variant="ghost" size="icon" aria-label="Refresh people" disabled={disabled} onClick={refresh}><RefreshCw className={`h-4 w-4 ${pending ? "motion-safe:animate-spin" : ""}`} aria-hidden="true" /></Button>
  </WorkspaceToolbar>;
}
