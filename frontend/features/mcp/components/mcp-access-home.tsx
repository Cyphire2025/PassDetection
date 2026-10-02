"use client";

import { useState, type ReactNode } from "react";
import { Copy, HelpCircle, ShieldCheck } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import type { McpOverview } from "../api/mcp.api";
import { useMcpConnections, useMcpControl } from "../hooks/use-mcp";
import { isMcpReadOnlyMode } from "../utils/read-only";
import { McpAccessExamples } from "./mcp-access-examples";
import { accessStatus, isGlobalConnectsClient } from "./mcp-access-model";
import { McpReadAccessPanel } from "./mcp-read-access-panel";
import { McpError, McpPagination } from "./mcp-shared";
import { McpDirectSetup } from "./mcp-direct-setup";

export function McpAccessHome({ overview, overviewUnavailable, onSetup, children }: {
  overview: McpOverview; overviewUnavailable: boolean; onSetup: () => void; children?: ReactNode;
}) {
  const user = useAuthStore(selectUser);
  const [offset, setOffset] = useState(0);
  const [guide, setGuide] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<unknown>(null);
  const [controlIntent, setControlIntent] = useState<boolean | null>(null);
  const connections = useMcpConnections(offset);
  const control = useMcpControl();
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
    {readOnly ? <p className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950"><strong>Read-only access.</strong> Codex can look up information in the sections you allow below. It cannot change records, send messages, upload files or export reports through this connection.</p> : null}
    <section aria-label="Codex connection status" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-3"><div className="rounded-lg bg-blue-50 p-2"><ShieldCheck className="h-5 w-5 text-blue-700" aria-hidden="true" /></div><div>
          <div className="flex flex-wrap items-center gap-2"><h2 className="text-base font-semibold text-slate-950">{connections.isPending ? "Checking access…" : status.title}</h2>{status.authorized ? <Badge variant="success" dot>Authorized</Badge> : null}</div>
          <p className="mt-2 max-w-xl text-sm leading-6 text-slate-600">{connections.isPending ? "Checking the saved connections for your account." : status.description}</p>
        </div></div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant={status.authorized ? "secondary" : "primary"} aria-expanded={guide} aria-controls="codex-connect-guide" onClick={() => setGuide(!guide)}><HelpCircle className="h-4 w-4" aria-hidden="true" />{status.authorized ? "How to connect" : "Connect Codex"}</Button>
          {overview.deployment_enabled ? <Button variant="ghost" disabled={overviewUnavailable || control.isPending} onClick={() => { control.reset(); setControlIntent(!overview.enabled); }}>{overview.enabled ? "Pause access" : "Resume access"}</Button> : null}
        </div>
      </div>
      <div className="flex flex-col gap-3 rounded-lg bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0"><p className="text-xs font-medium text-slate-500">Global Connects · Streamable HTTP</p><code className="mt-1 block break-all text-sm text-slate-800">{overview.resource}</code></div>
        <Button variant="secondary" size="sm" onClick={() => void copyUrl()}><Copy className="h-4 w-4" aria-hidden="true" />{copied ? "URL copied" : "Copy MCP URL"}</Button>
      </div>
      <McpError error={copyError} />
      <McpError error={connections.error} onRetry={() => void connections.refetch()} />
      <McpError error={control.error} />
      {partial ? <McpPagination offset={offset} nextOffset={connections.data?.next_offset ?? null} onChange={setOffset} disabled={connections.isFetching} label="Connection pages" /> : null}
      {guide ? <div id="codex-connect-guide" className="space-y-4 rounded-lg bg-slate-50 p-4">
        <h3 className="text-sm font-semibold text-slate-900">Connect ChatGPT or Codex in three steps</h3>
        <McpDirectSetup overview={overview} />
        <div className="flex flex-col items-start gap-2"><Button variant="secondary" onClick={onSetup}>Open setup instructions</Button><p className="text-xs text-slate-500">Advanced also contains client details and permission settings.</p></div>
      </div> : null}
    </section>
    {children}
    {readOnly ? <McpReadAccessPanel overview={overview} connections={own} uncertain={uncertain} overviewUnavailable={overviewUnavailable} /> : <McpAccessExamples overview={overview} connections={own} uncertain={uncertain} />}
    <ConfirmDialog isOpen={controlIntent !== null} title={controlIntent ? "Resume access for everyone?" : "Pause access for everyone?"}
      description={controlIntent ? "Saved connections that are still authorized will be able to use the permissions and section settings currently enabled on this website again." : readOnly ? "This pauses all Codex connections to this website, including other administrators’ connections, and stops new reads. Your records and saved connections are retained." : "This pauses all Codex connections to this website, including other administrators’ connections, and stops new calls and protected downloads. Your records and saved connections are retained."}
      confirmLabel={controlIntent ? "Resume access" : "Pause access"} variant={controlIntent ? "primary" : "danger"} isLoading={control.isPending}
      onClose={() => setControlIntent(null)} onConfirm={() => { if (controlIntent !== null) control.mutate(controlIntent, { onSuccess: () => setControlIntent(null), onError: () => setControlIntent(null) }); }} />
  </div>;
}
