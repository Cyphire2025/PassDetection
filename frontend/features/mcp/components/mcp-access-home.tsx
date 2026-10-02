"use client";

import { useState } from "react";
import { Copy, ShieldCheck } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import type { McpOverview } from "../api/mcp.api";
import { useMcpConnections } from "../hooks/use-mcp";
import { isMcpReadOnlyMode } from "../utils/read-only";
import { accessStatus, isGlobalConnectsClient } from "./mcp-access-model";
import { McpError, McpPagination } from "./mcp-shared";
import { McpDirectSetup } from "./mcp-direct-setup";

export function McpAccessHome({ overview, overviewUnavailable }: {
  overview: McpOverview; overviewUnavailable: boolean;
}) {
  const user = useAuthStore(selectUser);
  const [offset, setOffset] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<unknown>(null);
  const connections = useMcpConnections(offset);
  const own = (connections.data?.items ?? []).filter((connection) => connection.user_id === user?.id && isGlobalConnectsClient(connection.client_id));
  const uncertain = overviewUnavailable || connections.isPending || connections.isError;
  const partial = offset > 0 || connections.data?.next_offset != null;
  const status = accessStatus(overview, own, uncertain, partial);
  const readOnly = isMcpReadOnlyMode(overview);
  const copyUrl = async () => {
    setCopyError(null);
    try { await navigator.clipboard.writeText(overview.resource); setCopied(true); }
    catch { setCopyError(new Error("The MCP URL could not be copied. Select and copy it from the field.")); }
  };
  return <div className="space-y-6">
    <div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Connection setup</h2><p className="mt-1 text-sm leading-6 text-slate-600">Connect Global Connects directly from your app’s custom MCP settings.</p></div>
    <section aria-label="Codex connection status" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-3"><div className="rounded-lg bg-blue-50 p-2"><ShieldCheck className="h-5 w-5 text-blue-700" aria-hidden="true" /></div><div>
          <div className="flex flex-wrap items-center gap-2"><h2 className="text-base font-semibold text-slate-950">{connections.isPending ? "Checking access…" : status.title}</h2>{status.authorized ? <Badge variant="success" dot>Authorized</Badge> : null}</div>
          <p className="mt-2 max-w-xl text-sm leading-6 text-slate-600">{connections.isPending ? "Checking the saved connections for your account." : status.description}</p>
        </div></div>
      </div>
      <div className="flex flex-col gap-3 rounded-lg bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0"><p className="text-xs font-medium text-slate-500">Global Connects · Streamable HTTP</p><code className="mt-1 block break-all text-sm text-slate-800">{overview.resource}</code></div>
        <Button variant="secondary" size="sm" onClick={() => void copyUrl()}><Copy className="h-4 w-4" aria-hidden="true" />{copied ? "URL copied" : "Copy MCP URL"}</Button>
      </div>
      <McpError error={copyError} />
      <McpError error={connections.error} onRetry={() => void connections.refetch()} />
      {partial ? <McpPagination offset={offset} nextOffset={connections.data?.next_offset ?? null} onChange={setOffset} disabled={connections.isFetching} label="Connection pages" /> : null}
    </section>
    <McpDirectSetup overview={overview} />
    <section aria-label="Connection information" className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <h3 className="text-sm font-semibold text-slate-950">Connection information</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{readOnly ? "This deployment provides read access to the sections enabled in Settings." : "Approved connections receive the permissions selected by your administrator."} Access tokens last 15 minutes; authorization lasts up to seven days.</p>
      <details className="mt-4 border-t border-slate-100 pt-4 text-sm"><summary className="cursor-pointer font-medium text-slate-700">Supported clients and return addresses</summary><ul className="mt-3 space-y-3">{Object.entries({ ...overview.approved_clients, ...overview.direct_clients }).map(([id, redirects]) => <li key={id} className="break-all text-xs leading-5 text-slate-500"><strong className="text-slate-800">{overview.client_names?.[id] ?? id}</strong>{redirects.map((redirect) => <p key={redirect}>{redirect}</p>)}</li>)}</ul></details>
    </section>
  </div>;
}
