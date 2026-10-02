"use client";

import Link from "next/link";
import { Cable, ListFilter, Monitor, Plug, RefreshCw, Settings2 } from "lucide-react";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui";
import { useMcpOverview, useMcpRefresh } from "../hooks/use-mcp";
import { McpAccessBoundary, McpError } from "./mcp-shared";
import { McpDevices } from "./mcp-devices";
import { McpSettings } from "./mcp-settings";
import { McpAccessHome } from "./mcp-access-home";
import { McpRequests } from "./mcp-requests";

export type McpAdminSection = "devices" | "requests" | "settings" | "setup";
const SECTIONS = [
  { id: "devices", label: "Devices", href: "/admin/mcp", icon: Monitor },
  { id: "requests", label: "Requests", href: "/admin/mcp/requests", icon: ListFilter },
  { id: "settings", label: "Settings", href: "/admin/mcp/settings", icon: Settings2 },
  { id: "setup", label: "Connection setup", href: "/admin/mcp/setup", icon: Cable },
] as const;

export function McpAdminPage({ section = "devices" }: { section?: McpAdminSection }) {
  return <McpAccessBoundary><McpAdminWorkspace section={section} /></McpAccessBoundary>;
}

function McpAdminWorkspace({ section }: { section: McpAdminSection }) {
  const overview = useMcpOverview();
  const refresh = useMcpRefresh();
  const unavailable = overview.isError || overview.isFetching;
  return <div className="space-y-6">
    <WorkspacePageHeader icon={Plug} title="MCP access" description="Manage approved devices, review requests, and choose what ChatGPT and Codex can access."
      actions={<Button variant="secondary" isLoading={overview.isFetching} onClick={() => void refresh()}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh status</Button>} />
    <nav aria-label="MCP pages" className="grid grid-cols-2 gap-1 rounded-xl border border-slate-200 bg-white p-1.5 sm:flex">
      {SECTIONS.map(({ id, label, href, icon: Icon }) => <Link key={id} href={href} aria-current={section === id ? "page" : undefined}
        className={`flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors sm:justify-start sm:px-5 ${section === id ? "bg-blue-50 text-blue-800 ring-1 ring-inset ring-blue-100" : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"}`}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />{label}
      </Link>)}
    </nav>
    <McpError error={overview.error} onRetry={() => void overview.refetch()} />
    {overview.isPending ? <p role="status" className="text-sm text-slate-500">Checking access…</p> : null}
    {overview.data ? section === "devices" ? <McpDevices overview={overview.data} unavailable={unavailable} />
      : section === "requests" ? <McpRequests overview={overview.data} unavailable={unavailable} />
      : section === "settings" ? <McpSettings overview={overview.data} unavailable={unavailable} />
      : <McpAccessHome overview={overview.data} overviewUnavailable={unavailable} /> : null}
  </div>;
}
