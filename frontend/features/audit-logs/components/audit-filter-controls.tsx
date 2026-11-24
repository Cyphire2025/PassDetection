import { Download, FilterX } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { EMPTY_FILTERS, auditResultFilter } from "../audit-filter-model";
import type { AuditLedgerController } from "../hooks/use-audit-ledger";

export function AuditFilterControls({ controller }: { controller: AuditLedgerController; }) {
  const { role, filters, setFilters, isFiltered, exportLedger, canExport, exportMutation, updateFilter } = controller;
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" aria-labelledby="audit-filter-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="audit-filter-heading" className="mt-0.5 font-semibold text-slate-950">Filters</h2>
          <p className="mt-1 text-sm text-slate-600">Filter events by date, user, action, or result.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={() => setFilters(EMPTY_FILTERS)} disabled={!isFiltered}>
            <FilterX className="h-4 w-4" aria-hidden="true" /> Clear filters
          </Button>
          <Button type="button" onClick={() => { void exportLedger(); }} disabled={!canExport} isLoading={exportMutation.isPending}>
            <Download className="h-4 w-4" aria-hidden="true" /> Export CSV
          </Button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Input id="audit-start-at" type="datetime-local" label="Start time" value={filters.startAt} onChange={(event) => updateFilter("startAt", event.target.value)} />
        <Input id="audit-end-at" type="datetime-local" label="End time" value={filters.endAt} onChange={(event) => updateFilter("endAt", event.target.value)} />
        <Input id="audit-actor" label="Actor email or user ID" value={filters.actor} onChange={(event) => updateFilter("actor", event.target.value)} maxLength={255} autoComplete="off" />
        <Input id="audit-event-type" label="Event type" value={filters.eventType} onChange={(event) => updateFilter("eventType", event.target.value)} maxLength={80} autoComplete="off" placeholder="passport.deleted" />
        <Input id="audit-entity-type" label="Entity type" value={filters.entityType} onChange={(event) => updateFilter("entityType", event.target.value)} maxLength={80} autoComplete="off" />
        <Input id="audit-entity-id" label="Entity identifier" value={filters.entityId} onChange={(event) => updateFilter("entityId", event.target.value)} maxLength={128} autoComplete="off" />
        <label className="flex flex-col gap-1.5 text-sm font-medium text-slate-700" htmlFor="audit-result">
          Result
          <select id="audit-result" value={filters.result} onChange={(event) => updateFilter("result", auditResultFilter(event.target.value))} className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-600">
            <option value="">All results</option>
            <option value="success">Success</option>
            <option value="blocked">Blocked</option>
            <option value="denied">Denied</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        {role === "super_admin" && (
          <Input id="audit-agency-id" label="Agency ID" value={filters.agencyId} onChange={(event) => updateFilter("agencyId", event.target.value)} maxLength={36} autoComplete="off" placeholder="Optional agency ID" />
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">CSV export requires both times and is limited to 31 days and 10,000 rows per request.</p>
    </section>

  );
}
