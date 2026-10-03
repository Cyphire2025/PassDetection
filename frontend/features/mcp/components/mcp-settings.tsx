"use client";

import { useState } from "react";
import { Badge, Button } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import type { McpOverview } from "../api/mcp.api";
import { useMcpControl } from "../hooks/use-mcp";
import { isMcpReadOnlyMode } from "../utils/read-only";
import { McpReadAccessPanel } from "./mcp-read-access-panel";
import { McpPermissionsPanel } from "./mcp-permissions-panel";
import { McpError } from "./mcp-shared";
import { McpActivityPanel } from "./mcp-activity";
import { McpFiles, McpToolInventory, McpWorkflows } from "./mcp-work-results";

export function McpSettings({ overview, unavailable }: { overview: McpOverview; unavailable: boolean }) {
  const [intent, setIntent] = useState<boolean | null>(null);
  const [detail, setDetail] = useState<"activity" | "tools" | "workflows" | "files">("activity");
  const control = useMcpControl();
  const readOnly = isMcpReadOnlyMode(overview);
  const selectedDetail = readOnly && (detail === "workflows" || detail === "files") ? "activity" : detail;
  return <div className="space-y-6">
    <div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Settings</h2><p className="mt-1 text-sm leading-6 text-slate-600">Set the access policy for every approved MCP connection.</p></div>
    <section aria-label="MCP service settings" className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-5 p-5 sm:p-6"><div><h3 className="text-sm font-semibold text-slate-950">Allow MCP access</h3>
        <p className="mt-1 text-sm leading-6 text-slate-500">{overview.deployment_enabled ? "Pause or resume all approved connections. Device settings and saved permissions are retained." : "MCP access is unavailable on this deployment."}</p></div>
        <button type="button" role="switch" aria-label="Allow MCP access" aria-checked={overview.enabled}
          disabled={unavailable || !overview.deployment_enabled || control.isPending}
          onClick={() => { control.reset(); setIntent(!overview.enabled); }}
          className={`relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:opacity-50 ${overview.enabled ? "bg-blue-600" : "bg-slate-200"}`}>
          <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${overview.enabled ? "translate-x-5" : ""}`} />
        </button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 sm:px-6"><div><p className="text-sm font-medium text-slate-800">Connection permissions</p><p className="mt-1 text-xs text-slate-500">{readOnly ? "Reads are limited to the sections allowed below. Records cannot be changed through this deployment." : "Each approved device uses its own selected permissions."}</p></div><Badge variant="outline">{readOnly ? "Read only" : "Selected permissions"}</Badge></div>
      <div className="px-5 pb-4 sm:px-6"><McpError error={control.error} /></div>
    </section>
    {overview.permission_controls_available || !readOnly ? <McpPermissionsPanel unavailable={unavailable} /> : <>
      <McpReadAccessPanel overview={overview} connections={[]} uncertain={false} overviewUnavailable={unavailable} />
      <section aria-label="Write settings" className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6"><h2 className="text-base font-semibold text-slate-950">Write settings</h2><p className="mt-2 text-sm leading-6 text-slate-500">Write actions are unavailable on this deployment. Existing connections keep their read permissions.</p></section>
    </>}
    <section aria-label="Access monitoring" className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div><h3 className="text-base font-semibold text-slate-950">Access monitoring</h3><p className="mt-1 text-sm text-slate-500">Review recorded activity and the tools available to approved connections.</p></div>
      <nav aria-label="Access monitoring views" className="flex flex-wrap gap-2">
        {([ ["activity", "Activity"], ["tools", "Tools"], ...(!readOnly ? [["workflows", "Workflows"], ["files", "Files"]] : []) ] as [typeof detail, string][]).map(([key, label]) =>
          <Button key={key} variant={selectedDetail === key ? "primary" : "secondary"} size="sm" aria-current={selectedDetail === key ? "page" : undefined} onClick={() => setDetail(key)}>{label}</Button>)}
      </nav>
      {selectedDetail === "activity" ? <McpActivityPanel /> : selectedDetail === "tools" ? <McpToolInventory readOnly={readOnly} /> : selectedDetail === "files" && !readOnly ? <McpFiles /> : !readOnly ? <McpWorkflows /> : null}
    </section>
    <ConfirmDialog isOpen={intent !== null} title={intent ? "Resume access for everyone?" : "Pause access for everyone?"}
      description={intent ? "Approved devices can use the saved permissions and section settings again." : "This stops MCP access for every approved device. Your saved connections and application records are retained."}
      confirmLabel={intent ? "Resume access" : "Pause access"} variant={intent ? "primary" : "danger"} isLoading={control.isPending}
      onClose={() => setIntent(null)} onConfirm={() => { if (intent !== null) control.mutate(intent, { onSuccess: () => setIntent(null), onError: () => setIntent(null) }); }} />
  </div>;
}
