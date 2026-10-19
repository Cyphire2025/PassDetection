"use client";

import { useEffect, useState } from "react";
import { aiSettingsApi, type AssistantConfiguration, type McpConnections } from "../settings-api";

export function AssistantMcpSettings({ value, onChange }: { value: AssistantConfiguration; onChange: (value: AssistantConfiguration) => void }) {
  const [connections, setConnections] = useState<McpConnections["items"]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const abort = new AbortController();
    void aiSettingsApi.mcpConnections(abort.signal).then((result) => { if (!abort.signal.aborted) setConnections(result.items); })
      .catch(() => { if (!abort.signal.aborted) setError("MCP connections could not be loaded. Reload settings to retry."); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, []);
  return <section className="rounded-xl border border-slate-200 bg-white p-6" aria-labelledby="ai-mcp-settings-heading" aria-busy={loading}>
    <h3 id="ai-mcp-settings-heading" className="text-sm font-semibold text-slate-900">MCP access</h3>
    <p className="mt-2 text-sm leading-6 text-slate-500">The assistant discovers the tools allowed by your existing MCP connection. Read access is the default; every action is checked against current MCP permissions.</p>
    <label className="mt-5 block text-sm font-medium text-slate-700">MCP connection<select value={value.mcp_connection_id || ""} onChange={(event) => onChange({ ...value, mcp_connection_id: event.target.value || null })} className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-blue-500">
      <option value="">{connections.length === 1 ? `Automatic · ${connections[0].name}` : "Select an existing connection"}</option>
      {value.mcp_connection_id && !connections.some((item) => item.id === value.mcp_connection_id) ? <option value={value.mcp_connection_id}>Saved connection unavailable</option> : null}
      {connections.map((item) => <option key={item.id} value={item.id}>{item.name}{item.write_enabled ? "" : " · read access"}</option>)}
    </select></label>
    <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-4"><input type="checkbox" role="switch" className="mt-1 h-4 w-4 accent-blue-600" checked={value.mcp_write_enabled ?? false} onChange={(event) => onChange({ ...value, mcp_write_enabled: event.target.checked })} /><span><span className="block text-sm font-medium text-slate-800">Allow MCP write access for AI</span><span className="mt-1 block text-xs leading-5 text-slate-500">Allows requested changes through tools that MCP already permits. This switch changes only the assistant. Existing MCP permissions and connections stay as configured.</span></span></label>
    {error ? <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p> : null}
    {!connections.length && !error ? <p className="mt-3 text-xs text-slate-500">{loading ? "Loading existing connections…" : "No active MCP connection is available to this account."}</p> : null}
  </section>;
}
