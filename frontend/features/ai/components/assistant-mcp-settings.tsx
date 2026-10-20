"use client";

import { useEffect, useState } from "react";
import { aiSettingsApi, type AssistantConfiguration } from "../settings-api";
import type { McpAccessStatus } from "../types";

export function AssistantMcpSettings({ value, onChange }: { value: AssistantConfiguration; onChange: (value: AssistantConfiguration) => void }) {
  const [access, setAccess] = useState<McpAccessStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    void aiSettingsApi.mcpAccess(abort.signal).then((result) => { if (!abort.signal.aborted) setAccess(result.mcp); })
      .catch(() => { if (!abort.signal.aborted) setError("Workspace access could not be checked. Refresh workspace access to retry."); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [refresh]);
  return <section id="ai-mcp-access" className="rounded-xl border border-slate-200 bg-white p-6" aria-labelledby="ai-mcp-settings-heading" aria-busy={loading}>
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 id="ai-mcp-settings-heading" className="text-sm font-semibold text-slate-900">MCP access</h3>
      <button type="button" disabled={loading} onClick={() => { setLoading(true); setError(""); setRefresh((current) => current + 1); }} className="text-sm text-blue-700 disabled:opacity-50">Refresh workspace access</button></div>
    <p className="mt-2 text-sm leading-6 text-slate-500">Workspace tools connect through your signed-in account. Current MCP permissions apply, with read-only access by default.</p>
    <div className="mt-5 rounded-lg bg-slate-50 p-4 text-sm leading-6 text-slate-600">
      <h4 className="font-medium text-slate-800">Saved workspace access</h4>
      {error ? <p role="alert" className="mt-1 text-rose-700">{error}</p>
        : loading ? <p role="status" className="mt-1">Checking workspace access…</p>
        : <div role="status" className="mt-1">{access?.connected ? <>
          <p>{access.available_tools === undefined ? "Workspace tools available" : `${access.available_tools} workspace tools available`}</p>
          <p>{access.write_enabled ? "Write actions permitted by MCP are available to the assistant." : "Write actions are off for the assistant."}</p>
        </> : <p>{access?.message || "Workspace tools are unavailable. You can still chat and use your own attachments."}</p>}</div>}
    </div>
    <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-4"><input type="checkbox" role="switch" className="mt-1 h-4 w-4 accent-blue-600" checked={value.mcp_write_enabled ?? false} onChange={(event) => onChange({ ...value, mcp_write_enabled: event.target.checked })} /><span><span className="block text-sm font-medium text-slate-800">Allow MCP write access for AI</span><span className="mt-1 block text-xs leading-5 text-slate-500">Save AI settings to allow requested changes through tools that MCP already permits. This switch changes only the assistant; existing MCP permissions stay as configured.</span></span></label>
  </section>;
}
