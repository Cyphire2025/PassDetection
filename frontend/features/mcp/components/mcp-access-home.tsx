"use client";

import { useState } from "react";
import { HelpCircle, ShieldCheck } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import type { McpOverview } from "../api/mcp.api";
import { useMcpConnections, useMcpControl } from "../hooks/use-mcp";
import { isMcpReadOnlyMode } from "../utils/read-only";
import { McpAccessExamples } from "./mcp-access-examples";
import { accessStatus, CODEX_CALLBACK, CODEX_CLIENT_ID } from "./mcp-access-model";
import { McpConnectionCard } from "./mcp-connection-card";
import { McpReadAccessPanel } from "./mcp-read-access-panel";
import { McpError, McpPagination } from "./mcp-shared";

export function McpAccessHome({ overview, overviewUnavailable, onSetup }: {
  overview: McpOverview; overviewUnavailable: boolean; onSetup: () => void;
}) {
  const user = useAuthStore(selectUser);
  const [offset, setOffset] = useState(0);
  const [guide, setGuide] = useState(false);
  const [controlIntent, setControlIntent] = useState<boolean | null>(null);
  const connections = useMcpConnections(offset);
  const control = useMcpControl();
  const own = (connections.data?.items ?? []).filter((connection) => connection.user_id === user?.id && connection.client_id === CODEX_CLIENT_ID);
  const uncertain = overviewUnavailable || connections.isPending || connections.isError;
  const partial = offset > 0 || connections.data?.next_offset != null;
  const status = accessStatus(overview, own, uncertain, partial);
  const approved = overview.approved_clients[CODEX_CLIENT_ID]?.includes(CODEX_CALLBACK);
  const readOnly = isMcpReadOnlyMode(overview);
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
      <McpError error={connections.error} onRetry={() => void connections.refetch()} />
      <McpError error={control.error} />
      {own.length ? <div className="space-y-3 border-t border-slate-100 pt-4"><h3 className="text-sm font-medium text-slate-700">Your saved connections</h3>{own.map((connection) => <McpConnectionCard key={connection.id} connection={connection} readOnly={readOnly} unavailable={overviewUnavailable} />)}</div> : null}
      {partial ? <McpPagination offset={offset} nextOffset={connections.data?.next_offset ?? null} onChange={setOffset} disabled={connections.isFetching} label="Connection pages" /> : null}
      {guide ? <div id="codex-connect-guide" className="space-y-4 rounded-lg bg-slate-50 p-4">
        <h3 className="text-sm font-semibold text-slate-900">Connect Codex in three steps</h3>
        <ol className="grid gap-4 text-sm leading-6 text-slate-600 md:grid-cols-3">
          <li><p className="font-medium text-slate-900">1. Set up the connector</p><p>Use the Global Connects connector installed on your computer. For a first installation, get the reviewed package from your administrator.</p></li>
          <li><p className="font-medium text-slate-900">2. Sign in and choose access</p><p>{readOnly ? "Start sign-in from the connector. Confirm your identity in the browser and approve read access. The section settings below apply to every connection." : "Start sign-in from the connector. In your browser, confirm your identity and review permission to look up information or download reports."}</p></li>
          <li><p className="font-medium text-slate-900">3. Ask Codex</p><p>Open Codex with the connector configured and try an example below. Refresh this page to check the saved authorization.</p></li>
        </ol>
        {!approved ? <p role="status" className="text-sm text-amber-800">The desktop connector is not approved on this website yet. Ask your administrator to complete its setup.</p> : null}
        <div className="flex flex-col items-start gap-2"><Button variant="secondary" onClick={onSetup}>Open setup instructions</Button><p className="text-xs text-slate-500">The instructions are in Advanced. This website does not install or configure Codex for you.</p></div>
      </div> : null}
    </section>
    {readOnly ? <McpReadAccessPanel overview={overview} connections={own} uncertain={uncertain} overviewUnavailable={overviewUnavailable} /> : <McpAccessExamples overview={overview} connections={own} uncertain={uncertain} />}
    <ConfirmDialog isOpen={controlIntent !== null} title={controlIntent ? "Resume access for everyone?" : "Pause access for everyone?"}
      description={controlIntent ? "Saved connections that are still authorized will be able to use the permissions and section settings currently enabled on this website again." : readOnly ? "This pauses all Codex connections to this website, including other administrators’ connections, and stops new reads. Your records and saved connections are retained." : "This pauses all Codex connections to this website, including other administrators’ connections, and stops new calls and protected downloads. Your records and saved connections are retained."}
      confirmLabel={controlIntent ? "Resume access" : "Pause access"} variant={controlIntent ? "primary" : "danger"} isLoading={control.isPending}
      onClose={() => setControlIntent(null)} onConfirm={() => { if (controlIntent !== null) control.mutate(controlIntent, { onSuccess: () => setControlIntent(null), onError: () => setControlIntent(null) }); }} />
  </div>;
}
