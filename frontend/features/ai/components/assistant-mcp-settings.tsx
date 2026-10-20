"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { aiSettingsApi, type AssistantConfiguration, type McpConnections } from "../settings-api";

export function AssistantMcpSettings({ value, onChange }: { value: AssistantConfiguration; onChange: (value: AssistantConfiguration) => void }) {
  const [connections, setConnections] = useState<McpConnections["items"]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    void aiSettingsApi.mcpConnections(abort.signal).then((result) => { if (!abort.signal.aborted) setConnections(result.items); })
      .catch(() => { if (!abort.signal.aborted) setError("MCP connections could not be loaded. Refresh connections to retry."); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [refresh]);
  const selected = connections.find((item) => item.id === value.mcp_connection_id);
  const unavailable = !loading && !error && Boolean(value.mcp_connection_id) && !selected;
  const empty = !loading && !error && !connections.length;
  const needsSelection = !loading && !error && !value.mcp_connection_id && connections.length > 1;
  return <section id="ai-mcp-access" className="rounded-xl border border-slate-200 bg-white p-6" aria-labelledby="ai-mcp-settings-heading" aria-busy={loading}>
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 id="ai-mcp-settings-heading" className="text-sm font-semibold text-slate-900">MCP access</h3>
      <button type="button" disabled={loading} onClick={() => { setLoading(true); setError(""); setRefresh((current) => current + 1); }} className="text-sm text-blue-700 disabled:opacity-50">Refresh connections</button></div>
    <p className="mt-2 text-sm leading-6 text-slate-500">The assistant discovers the tools allowed by your existing MCP connection. Read access is the default; every action is checked against current MCP permissions.</p>
    <label className="mt-5 block text-sm font-medium text-slate-700">MCP connection<select value={value.mcp_connection_id || ""} disabled={loading || Boolean(error) || !connections.length} aria-describedby="ai-mcp-connection-status" onChange={(event) => onChange({ ...value, mcp_connection_id: event.target.value || null })} className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-blue-500 disabled:bg-slate-50">
      <option value="">{loading ? "Loading existing connections…" : error ? "Connection list unavailable" : connections.length === 1 ? "Automatic · " + connections[0].name : connections.length ? "Choose a connection for workspace tools" : "No active authorized connections"}</option>
      {value.mcp_connection_id && !connections.some((item) => item.id === value.mcp_connection_id) ? <option value={value.mcp_connection_id}>{loading || error ? "Saved connection (not verified)" : "Saved connection unavailable"}</option> : null}
      {connections.map((item) => <option key={item.id} value={item.id}>{item.name}{item.read_enabled ? item.write_enabled ? " · read and write permitted" : " · read permitted" : item.write_enabled ? " · write permitted; reads disabled" : " · data access disabled"}</option>)}
    </select></label>
    <div id="ai-mcp-connection-status" className="mt-3 text-sm leading-6 text-slate-600">
      {error ? <p role="alert" className="text-rose-700">{error}</p>
        : loading ? <p role="status">Checking existing connections…</p>
        : empty ? <><p role="status">No active authorized MCP connection is available to this account. Workspace tools are unavailable; you can still chat and use your own attachments.</p><Link href="/admin/mcp/setup" className="font-medium text-blue-700 underline">Reconnect existing MCP connection</Link></>
        : unavailable ? <p role="status">The saved connection is unavailable. Choose an existing connection above and save AI settings.</p>
        : needsSelection ? <p role="status">More than one connection is available. Choose which connection the assistant should use, then save AI settings.</p>
        : !value.mcp_connection_id ? <p>Using your only available connection automatically.</p> : null}
    </div>
    <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-4"><input type="checkbox" role="switch" className="mt-1 h-4 w-4 accent-blue-600" checked={value.mcp_write_enabled ?? false} onChange={(event) => onChange({ ...value, mcp_write_enabled: event.target.checked })} /><span><span className="block text-sm font-medium text-slate-800">Allow MCP write access for AI</span><span className="mt-1 block text-xs leading-5 text-slate-500">Allows requested changes through tools that MCP already permits. This switch changes only the assistant. Existing MCP permissions and connections stay as configured.</span></span></label>
  </section>;
}
