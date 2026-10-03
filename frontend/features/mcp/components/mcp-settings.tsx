"use client";

import { useState } from "react";
import { Activity, FileText, GitBranch, ListChecks, Settings2, ShieldCheck, SquarePen } from "lucide-react";
import { Badge } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import type { McpOverview } from "../api/mcp.api";
import { useMcpControl } from "../hooks/use-mcp";
import { isMcpReadOnlyMode } from "../utils/read-only";
import { McpReadAccessPanel } from "./mcp-read-access-panel";
import { McpPermissionsPanel } from "./mcp-permissions-panel";
import { McpError } from "./mcp-shared";
import { McpActivityPanel } from "./mcp-activity";
import { McpFiles, McpToolInventory, McpWorkflows } from "./mcp-work-results";

const SETTINGS_VIEWS = [
  { id: "general", label: "General", icon: Settings2, group: "Access policy", writeOnly: false },
  { id: "read", label: "Read access", icon: ShieldCheck, group: "Access policy", writeOnly: false },
  { id: "write", label: "Write access", icon: SquarePen, group: "Access policy", writeOnly: true },
  { id: "activity", label: "Activity", icon: Activity, group: "Monitoring", writeOnly: false },
  { id: "tools", label: "Tools", icon: ListChecks, group: "Monitoring", writeOnly: false },
  { id: "workflows", label: "Workflows", icon: GitBranch, group: "Monitoring", writeOnly: true },
  { id: "files", label: "Files", icon: FileText, group: "Monitoring", writeOnly: true },
] as const;
type SettingsView = typeof SETTINGS_VIEWS[number]["id"];

export function McpSettings({ overview, unavailable }: { overview: McpOverview; unavailable: boolean }) {
  const [intent, setIntent] = useState<boolean | null>(null);
  const [view, setView] = useState<SettingsView>("general");
  const control = useMcpControl();
  const readOnly = isMcpReadOnlyMode(overview);
  const views = SETTINGS_VIEWS.filter((item) => !readOnly || !item.writeOnly);
  const selected = views.find((item) => item.id === view) ?? views[0];
  const permissionsVisible = selected.id === "read" || selected.id === "write";
  return <div className="space-y-5">
    <div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Settings</h2><p className="mt-1 text-sm leading-6 text-slate-600">Manage access policies and review MCP activity.</p></div>
    <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="MCP settings" className="rounded-xl border border-slate-200 bg-white p-3 lg:sticky lg:top-6">
        {(["Access policy", "Monitoring"] as const).map((group) => <div key={group} className="last:mt-4">
          <p className="px-3 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{group}</p>
          <div className="flex flex-wrap gap-1 lg:flex-col">
            {views.filter((item) => item.group === group).map(({ id, label, icon: Icon }) => <button key={id} id={`mcp-settings-${id}`} type="button"
              aria-current={selected.id === id ? "page" : undefined} aria-controls="mcp-settings-content" onClick={() => setView(id)}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${selected.id === id ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"}`}>
              <Icon aria-hidden="true" className="h-4 w-4 shrink-0" />{label}
            </button>)}
          </div>
        </div>)}
      </nav>
      <div id="mcp-settings-content" role="region" aria-labelledby={`mcp-settings-${selected.id}`} className="min-w-0 space-y-5">
        {selected.id === "general" ? <section aria-label="MCP service settings" className="rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 p-5 sm:p-6"><h3 className="text-lg font-semibold tracking-tight text-slate-950">General</h3><p className="mt-1 text-sm leading-6 text-slate-500">Control access across every approved device.</p></div>
          <div className="flex items-center justify-between gap-5 p-5 sm:p-6"><div><h4 className="text-sm font-semibold text-slate-950">Allow MCP access</h4>
            <p className="mt-1 text-sm leading-6 text-slate-500">{overview.deployment_enabled ? "Pause or resume all approved connections. Your device permissions and section choices are saved." : "MCP access is unavailable on this deployment."}</p></div>
            <button type="button" role="switch" aria-label="Allow MCP access" aria-checked={overview.enabled}
              disabled={unavailable || !overview.deployment_enabled || control.isPending}
              onClick={() => { control.reset(); setIntent(!overview.enabled); }}
              className={`relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:opacity-50 ${overview.enabled ? "bg-blue-600" : "bg-slate-200"}`}>
              <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${overview.enabled ? "translate-x-5" : ""}`} />
            </button>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 sm:px-6"><div><p className="text-sm font-medium text-slate-800">Device permissions</p><p className="mt-1 text-xs leading-5 text-slate-500">{readOnly ? "Devices can read only the sections you allow in Read access." : "Read and Write settings apply to all devices. Each device also needs its own allowances and approved permissions."}</p></div><Badge variant="outline">{readOnly ? "Read only" : "Per-device controls"}</Badge></div>
          <div className="px-5 pb-4 sm:px-6"><McpError error={control.error} /></div>
        </section> : null}
        {/* Keep one editor mounted so changing views retains the shared Read/Write draft. */}
        <div hidden={!permissionsVisible}>
          {overview.permission_controls_available || !readOnly ? <McpPermissionsPanel unavailable={unavailable} mode={selected.id === "write" ? "write" : "read"} />
            : <McpReadAccessPanel overview={overview} connections={[]} uncertain={false} overviewUnavailable={unavailable} />}
        </div>
        {selected.id === "activity" ? <McpActivityPanel /> : selected.id === "tools" ? <McpToolInventory readOnly={readOnly} />
          : selected.id === "files" ? <McpFiles /> : selected.id === "workflows" ? <McpWorkflows /> : null}
      </div>
    </div>
    <ConfirmDialog isOpen={intent !== null} title={intent ? "Resume access for everyone?" : "Pause access for everyone?"}
      description={intent ? "Approved devices can use the saved permissions and section settings again." : "This stops MCP access for every approved device. Your saved connections and application records are retained."}
      confirmLabel={intent ? "Resume access" : "Pause access"} variant={intent ? "primary" : "danger"} isLoading={control.isPending}
      onClose={() => setIntent(null)} onConfirm={() => { if (intent !== null) control.mutate(intent, { onSuccess: () => setIntent(null), onError: () => setIntent(null) }); }} />
  </div>;
}
