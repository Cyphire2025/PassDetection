"use client";

import { useDeferredValue, useState } from "react";
import { Badge, Input } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { useMcpActivity } from "../hooks/use-mcp";
import { McpError, McpPagination } from "./mcp-shared";

export function McpActivityPanel() {
  const [filter, setFilter] = useState({ search: "", offset: 0 });
  const deferredFilter = useDeferredValue(filter);
  const query = useMcpActivity(deferredFilter.offset, deferredFilter.search);
  return <section aria-label="MCP activity history" className="space-y-4">
    <Input type="search" label="Search activity actions" placeholder="For example, mcp.revoked" maxLength={120} value={filter.search}
      onChange={(event) => setFilter({ search: event.target.value, offset: 0 })} />
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading activity…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No matching activity found.</p> : null}
    <div className="divide-y divide-slate-100">{query.data?.items.map((item) => <article key={item.id} className="flex flex-wrap items-start justify-between gap-3 py-4 text-sm">
      <div className="min-w-0"><p className="break-words font-medium text-slate-900">{item.action}</p><p className="mt-1 break-all text-xs text-slate-500">{item.entity_id ? `Record ${item.entity_id}` : "Connection administration"}</p></div>
      <div className="text-right"><Badge variant={item.result === "success" ? "success" : "outline"}>{item.result}</Badge><p className="mt-1 text-xs text-slate-500">{formatDateTime(item.created_at)}</p></div>
    </article>)}</div>
    <McpPagination offset={deferredFilter.offset} nextOffset={query.data?.next_offset ?? null} onChange={(offset) => setFilter((current) => ({ ...current, offset }))} disabled={query.isFetching || filter !== deferredFilter} label="Activity pages" />
  </section>;
}
