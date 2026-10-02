"use client";

import { useState } from "react";
import { Monitor } from "lucide-react";
import type { McpOverview } from "../api/mcp.api";
import { useMcpConnections } from "../hooks/use-mcp";
import { isMcpReadOnlyMode } from "../utils/read-only";
import { McpConnectionCard } from "./mcp-connection-card";
import { McpError, McpPagination } from "./mcp-shared";

export function McpDevices({ overview, unavailable }: { overview: McpOverview; unavailable: boolean }) {
  const [offset, setOffset] = useState(0);
  const query = useMcpConnections(offset);
  return <section aria-label="MCP devices" className="space-y-5">
    <div className="flex items-start gap-3"><Monitor className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" aria-hidden="true" /><div>
      <h2 className="text-xl font-semibold tracking-tight text-slate-950">Devices</h2>
      <p className="mt-1 text-sm leading-6 text-slate-600">Each named authorization is listed separately. Disable a connection to stop its access; enable it to resume while its sign-in is valid.</p>
    </div></div>
    <p className="max-w-4xl text-xs leading-5 text-slate-500">These entries represent separate approved connections. Names and platforms are labels; ChatGPT may share one account connection across devices.</p>
    {!overview.enabled || overview.emergency_disabled ? <p role="status" className="text-sm text-amber-800">Access is paused for everyone. Enabling a device saves its setting; access resumes after the global pause is lifted.</p> : null}
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading devices…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">No approved devices yet. Add Global Connects in your app and approve its request on the Requests page.</p> : null}
    {query.data?.items.length ? <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_auto] gap-5 border-b border-slate-200 bg-slate-50 px-5 py-3 text-xs font-medium text-slate-500 lg:grid"><span>Device and access</span><span>Last used</span><span>Sign in again by</span><span className="min-w-28 text-right">Actions</span></div>
      <div className="divide-y divide-slate-100">{query.data.items.map((connection) => <McpConnectionCard key={connection.id} connection={connection} readOnly={isMcpReadOnlyMode(overview)} unavailable={unavailable || query.isError || query.isFetching} />)}</div>
    </div> : null}
    <McpPagination offset={offset} nextOffset={query.data?.next_offset ?? null} onChange={setOffset} disabled={query.isFetching} label="Device pages" />
  </section>;
}
