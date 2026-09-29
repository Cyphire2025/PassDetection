"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { canAccessApplicationPath } from "@/features/auth/config/route-capabilities";
import { ROUTES } from "@/constants/routes";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { MCP_CAPABILITIES, type McpCapability } from "../api/mcp.api";

export function McpAccessBoundary({ children }: { children: ReactNode }) {
  const user = useAuthStore(selectUser);
  return canAccessApplicationPath(user, ROUTES.dashboard.mcp) ? children
    : <p role="alert" className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-700">MCP administration requires an active superadmin account.</p>;
}
export function mcpErrorMessage(error: unknown) {
  return typeof error === "object" && error !== null && "message" in error && typeof error.message === "string"
    ? error.message : "The request could not be completed. Refresh and try again.";
}
export function McpError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  return <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
    <p>{mcpErrorMessage(error)}</p>
    {onRetry ? <Button type="button" variant="secondary" size="sm" className="mt-2" onClick={onRetry}>Retry</Button> : null}
  </div>;
}
export function McpCapabilityPicker({ available, selected, onChange, disabled = false }: {
  available: readonly McpCapability[]; selected: readonly McpCapability[];
  onChange: (capabilities: McpCapability[]) => void; disabled?: boolean;
}) {
  return <fieldset disabled={disabled} className="space-y-2">
    <legend className="mb-2 text-sm font-semibold text-slate-900">Connection permissions</legend>
    {available.map((capability) => <label key={capability} className="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm has-checked:border-blue-300 has-checked:bg-blue-50/40">
      <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-blue-600" checked={selected.includes(capability)}
        onChange={(event) => onChange(event.target.checked ? [...selected, capability] : selected.filter((item) => item !== capability))} />
      <span><span className="block font-medium text-slate-900">{MCP_CAPABILITIES[capability]?.label ?? capability}</span>
        <span className="mt-0.5 block text-xs leading-5 text-slate-500">{MCP_CAPABILITIES[capability]?.description}</span></span>
    </label>)}
  </fieldset>;
}
export function McpPagination({ offset, nextOffset, onChange, disabled = false, label }: {
  offset: number; nextOffset: number | null; onChange: (offset: number) => void; disabled?: boolean; label: string;
}) {
  if (offset === 0 && nextOffset === null) return null;
  return <nav aria-label={label} className="flex items-center justify-between gap-3 border-t border-slate-200 pt-4 text-xs text-slate-500">
    <span>Page {Math.floor(offset / 25) + 1}</span><div className="flex gap-2">
      <Button variant="secondary" size="sm" disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - 25))}>Previous</Button>
      <Button variant="secondary" size="sm" disabled={disabled || nextOffset === null} onClick={() => nextOffset !== null && onChange(nextOffset)}>Next</Button>
    </div>
  </nav>;
}
