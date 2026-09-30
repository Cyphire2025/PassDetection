"use client";

import { useEffect, useState } from "react";
import { ChevronDown, Plug, RefreshCw } from "lucide-react";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui";
import { useMcpOverview, useMcpRefresh } from "../hooks/use-mcp";
import { McpAccessHome } from "./mcp-access-home";
import { McpAdvanced, type McpAdvancedTab } from "./mcp-advanced";
import { McpAccessBoundary, McpError } from "./mcp-shared";

export function McpAdminPage() {
  return <McpAccessBoundary><McpAdminWorkspace /></McpAccessBoundary>;
}

function McpAdminWorkspace() {
  const overview = useMcpOverview();
  const refresh = useMcpRefresh();
  const [advanced, setAdvanced] = useState(false);
  const [tab, setTab] = useState<McpAdvancedTab>("connections");
  const [setupRequest, setSetupRequest] = useState(0);
  useEffect(() => {
    if (!setupRequest) return;
    const content = document.getElementById("codex-advanced-content");
    content?.focus();
    content?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [setupRequest]);
  return <div className="space-y-6">
    <WorkspacePageHeader icon={Plug} title="Codex access" description="Look up your work and prepare passport Excel reports from Codex."
      actions={<Button variant="secondary" isLoading={overview.isFetching} onClick={() => void refresh()}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh status</Button>} />
    <McpError error={overview.error} onRetry={() => void overview.refetch()} />
    {overview.isPending ? <p role="status" className="text-sm text-slate-500">Checking access…</p> : null}
    {overview.data ? <>
      <McpAccessHome overview={overview.data} overviewUnavailable={overview.isError} onSetup={() => { setTab("setup"); setAdvanced(true); setSetupRequest((value) => value + 1); }} />
      <section aria-label="Advanced Codex settings" className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
        <button type="button" aria-expanded={advanced} aria-controls="codex-advanced-content" onClick={() => setAdvanced(!advanced)}
          className="flex w-full items-center justify-between gap-3 text-left text-sm font-semibold text-slate-800">
          Advanced<ChevronDown aria-hidden="true" className={`h-4 w-4 transition-transform ${advanced ? "rotate-180" : ""}`} />
        </button>
        <p className="mt-1 text-xs leading-5 text-slate-500">Setup instructions, all connections, saved work and technical details.</p>
        {advanced ? <McpAdvanced overview={overview.data} tab={tab} onTabChange={setTab} /> : null}
      </section>
    </> : null}
  </div>;
}
