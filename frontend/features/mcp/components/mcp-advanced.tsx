"use client";

import { useDeferredValue, useState } from "react";
import { Copy } from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { MCP_CAPABILITIES, type McpOverview } from "../api/mcp.api";
import { useMcpActivity, useMcpConnections } from "../hooks/use-mcp";
import { McpConnectionCard } from "./mcp-connection-card";
import { McpConnectorSetup } from "./mcp-connector-setup";
import { McpError, McpPagination } from "./mcp-shared";
import { McpFiles, McpToolInventory, McpWorkflows } from "./mcp-work-results";

export type McpAdvancedTab = "connections" | "activity" | "workflows" | "files" | "tools" | "setup";

export function McpAdvanced({ overview, tab, onTabChange }: {
  overview: McpOverview; tab: McpAdvancedTab; onTabChange: (tab: McpAdvancedTab) => void;
}) {
  return <div id="codex-advanced-content" tabIndex={-1} className="space-y-5 border-t border-slate-200 pt-5">
    <div className="rounded-lg bg-slate-50 p-4 text-xs leading-5 text-slate-600">
      <p>Environment: {overview.environment} · Checked {formatDateTime(overview.observed_at)}</p>
      <p className="break-all">Release revision: {overview.revision ?? "Not reported"}</p>
      {overview.qualification !== "qualified" ? <p className="mt-2">Release qualification is in progress. A registered tool does not confirm that every workflow is available or fully qualified.</p> : null}
    </div>
    <nav aria-label="MCP administration sections" className="flex flex-wrap gap-1 border-b border-slate-200">
      {([["connections", "Connections"], ["activity", "Activity"], ["workflows", "Workflows"], ["files", "Files"], ["tools", "Tools"], ["setup", "Connection setup"]] as const).map(([key, label]) =>
        <button key={key} type="button" aria-current={tab === key ? "page" : undefined} onClick={() => onTabChange(key)}
          className={`border-b-2 px-3 py-2 text-sm font-medium ${tab === key ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-900"}`}>{label}</button>)}
    </nav>
    {tab === "connections" ? <Connections /> : tab === "activity" ? <Activity /> : tab === "workflows" ? <McpWorkflows /> : tab === "files" ? <McpFiles /> : tab === "tools" ? <McpToolInventory /> : <Setup overview={overview} />}
  </div>;
}

function Connections() {
  const [offset, setOffset] = useState(0);
  const query = useMcpConnections(offset);
  return <section aria-label="MCP connections" className="space-y-4">
    <div><h2 className="text-base font-semibold text-slate-900">Named connections</h2><p className="mt-1 text-sm text-slate-500">Each connection expires within seven days and can be revoked independently.</p></div>
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading connections…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No connections on this page. Start sign-in from an approved MCP client to create one.</p> : null}
    {query.data?.items.map((connection) => <McpConnectionCard key={connection.id} connection={connection} advanced />)}
    <McpPagination offset={offset} nextOffset={query.data?.next_offset ?? null} onChange={setOffset} disabled={query.isFetching} label="Connection pages" />
  </section>;
}

function Activity() {
  const [filter, setFilter] = useState({ search: "", offset: 0 });
  const deferredFilter = useDeferredValue(filter);
  const query = useMcpActivity(deferredFilter.offset, deferredFilter.search);
  return <section aria-label="MCP activity history" className="space-y-4">
    <Input type="search" label="Search activity actions" placeholder="For example, mcp.revoked" maxLength={120} value={filter.search}
      onChange={(event) => setFilter({ search: event.target.value, offset: 0 })} />
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading activity…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No matching activity found.</p> : null}
    <div className="divide-y divide-slate-200">{query.data?.items.map((item) => <article key={item.id} className="flex flex-wrap items-start justify-between gap-3 py-4 text-sm">
      <div className="min-w-0"><p className="break-words font-medium text-slate-900">{item.action}</p><p className="mt-1 break-all text-xs text-slate-500">{item.entity_id ? `Record ${item.entity_id}` : "Connection administration"}</p></div>
      <div className="text-right"><Badge variant={item.result === "success" ? "success" : "outline"}>{item.result}</Badge><p className="mt-1 text-xs text-slate-500">{formatDateTime(item.created_at)}</p></div>
    </article>)}</div>
    <McpPagination offset={deferredFilter.offset} nextOffset={query.data?.next_offset ?? null} onChange={(offset) => setFilter((current) => ({ ...current, offset }))} disabled={query.isFetching || filter !== deferredFilter} label="Activity pages" />
  </section>;
}

function Setup({ overview }: { overview: McpOverview }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<unknown>(null);
  const copyEndpoint = async () => {
    setCopyError(null);
    try { await navigator.clipboard.writeText(overview.resource); setCopied(true); }
    catch { setCopyError(new Error("The endpoint could not be copied. Select and copy it from the field above.")); }
  };
  return <section aria-label="MCP setup" className="grid gap-5 lg:grid-cols-2">
    <div className="space-y-4 rounded-xl border border-slate-200 p-5"><h2 className="text-base font-semibold text-slate-900">Connect your client</h2>
      <p className="text-sm leading-6 text-slate-600">Use the endpoint below in an approved authenticated MCP client. Start sign-in from the client, then review the connection name and permissions in your browser.</p>
      <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs font-medium text-slate-500">Streamable HTTP endpoint</p><code className="mt-2 block break-all text-xs text-slate-800">{overview.resource}</code></div>
      <Button variant="secondary" onClick={() => void copyEndpoint()}><Copy className="h-4 w-4" aria-hidden="true" />{copied ? "Endpoint copied" : "Copy endpoint"}</Button>
      <McpError error={copyError} />
      <details className="text-sm"><summary className="cursor-pointer font-medium text-slate-700">Approved clients</summary><ul className="mt-3 space-y-2">{Object.entries(overview.approved_clients).map(([id, redirects]) => <li key={id} className="break-all text-xs text-slate-500"><strong className="text-slate-700">{id}</strong>{redirects.map((redirect) => <p key={redirect} className="mt-1">{redirect}</p>)}</li>)}</ul></details>
      <p className="text-xs leading-5 text-slate-500">Access tokens last 15 minutes. Authorization lasts up to seven days. Revoke a connection to require a fresh sign-in.</p>
    </div>
    <div className="rounded-xl border border-slate-200 p-5"><h2 className="text-base font-semibold text-slate-900">Permission categories</h2>
      <p className="mt-1 text-xs leading-5 text-slate-500">Connections only receive the permissions you select. Workflow availability is qualified separately.</p>
      <dl className="mt-4 divide-y divide-slate-100">{overview.capabilities.map((capability) => <div key={capability} className="py-3"><dt className="text-sm font-medium text-slate-900">{MCP_CAPABILITIES[capability]?.label ?? capability}</dt><dd className="mt-1 text-xs leading-5 text-slate-500">{MCP_CAPABILITIES[capability]?.description}</dd></div>)}</dl>
      <p className="mt-4 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">MCP cannot delete or remove application data, control the server, or change its own connection permissions.</p>
    </div>
    <McpConnectorSetup overview={overview} />
  </section>;
}
