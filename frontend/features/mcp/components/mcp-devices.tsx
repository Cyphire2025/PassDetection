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
  return <section aria-label="MCP devices" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
    <div className="flex items-start gap-3"><Monitor className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" aria-hidden="true" /><div>
      <h2 className="text-base font-semibold text-slate-950">Devices</h2>
      <p className="mt-1 text-sm leading-6 text-slate-600">Each named authorization is listed separately. Disable a connection to stop its access; enable it to resume while its sign-in is valid.</p>
    </div></div>
    <p className="rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">These are authorized connections with names and platforms you choose. ChatGPT may use one account connection across several devices. A separate sign-in creates a separate entry; the server cannot prove which physical computer is using it.</p>
    {!overview.enabled || overview.emergency_disabled ? <p role="status" className="text-sm text-amber-800">Access is paused for everyone. Enabling a device saves its setting; access resumes after the global pause is lifted.</p> : null}
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading devices…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">No connections on this page. Add the MCP URL in ChatGPT or Codex and complete sign-in to create an entry.</p> : null}
    {query.data?.items.map((connection) => <McpConnectionCard key={connection.id} connection={connection} readOnly={isMcpReadOnlyMode(overview)} unavailable={unavailable || query.isError || query.isFetching} />)}
    <McpPagination offset={offset} nextOffset={query.data?.next_offset ?? null} onChange={setOffset} disabled={query.isFetching} label="Device pages" />
  </section>;
}
