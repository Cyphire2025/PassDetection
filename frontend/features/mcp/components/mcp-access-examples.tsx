"use client";

import { useState } from "react";
import { Copy, FileSpreadsheet, Search } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { McpConnection, McpOverview } from "../api/mcp.api";
import { useMcpInventory } from "../hooks/use-mcp";
import { BUSINESS_EXAMPLES, exampleAvailable, hasPermission } from "./mcp-access-model";
import { McpError } from "./mcp-shared";

export function McpAccessExamples({ overview, connections, uncertain }: {
  overview: McpOverview; connections: McpConnection[]; uncertain: boolean;
}) {
  const inventory = useMcpInventory();
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<unknown>(null);
  const copy = async (key: string, prompt: string) => {
    setCopyError(null);
    try { await navigator.clipboard.writeText(prompt); setCopied(key); }
    catch { setCopyError(new Error("The example could not be copied. Select the text and copy it instead.")); }
  };
  return <section aria-label="What Codex can help with" className="space-y-3">
    <div><h2 className="text-base font-semibold text-slate-900">What Codex can help with</h2>
      <p className="mt-1 text-sm text-slate-500">Copy an example into Codex. It will ask for the details it needs.</p></div>
    <McpError error={inventory.error} onRetry={() => void inventory.refetch()} />
    <div className="grid gap-4 lg:grid-cols-2">{BUSINESS_EXAMPLES.map((example) => {
      const available = !inventory.isError && exampleAvailable(overview, inventory.data, example);
      const ready = !uncertain && overview.enabled && !overview.emergency_disabled && available && hasPermission(connections, example.capabilities);
      const Icon = example.key === "read" ? Search : FileSpreadsheet;
      const state = inventory.isPending ? "Checking availability" : !available ? "Not available here" : uncertain ? "Check access first" : !overview.enabled || overview.emergency_disabled ? "Access paused" : !hasPermission(connections, example.capabilities) ? "Permission needed" : "Authorized";
      return <article key={example.key} aria-label={example.title} className="flex flex-col rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center gap-2"><Icon className="h-5 w-5 text-blue-600" aria-hidden="true" /><h3 className="text-sm font-semibold text-slate-900">{example.title}</h3><Badge variant={ready ? "success" : "outline"}>{state}</Badge></div>
        <p className="mt-3 text-sm leading-6 text-slate-600">{example.description}</p>
        {available ? <>
          <p className="mt-4 flex-1 rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700">“{example.prompt}”</p>
          {example.key === "export" ? <p className="mt-2 text-xs leading-5 text-slate-500">Saving to your computer needs a download folder chosen in the local connector setup.</p> : null}
          <div className="mt-4"><Button variant="secondary" size="sm" disabled={!ready} onClick={() => void copy(example.key, example.prompt)}><Copy className="h-4 w-4" aria-hidden="true" />{copied === example.key ? "Example copied" : "Copy example"}</Button></div>
        </> : <p className="mt-4 text-xs leading-5 text-slate-500">{inventory.isPending ? "Checking which workflows this website supports…" : "This example is unavailable until its required features can be confirmed."}</p>}
      </article>;
    })}</div>
    <McpError error={copyError} />
    <p className="text-xs leading-5 text-slate-500">These examples look up information or prepare reports. They do not send messages or edit traveller details.</p>
  </section>;
}
