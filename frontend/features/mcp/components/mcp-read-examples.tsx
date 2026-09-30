"use client";

import { useState } from "react";
import { Badge, Button } from "@/components/ui";
import type { McpConnection, McpOverview, McpReadAccess } from "../api/mcp.api";
import { useMcpInventory } from "../hooks/use-mcp";
import { effectiveMcpCapabilities } from "../utils/read-only";
import { hasPermission } from "./mcp-access-model";
import { McpError } from "./mcp-shared";

const EXAMPLES = [
  { title: "Find groups", tools: ["list_groups"], prompt: "Show the groups available to my account, including their stored passenger and WhatsApp counts. Do not change anything." },
  { title: "Read a passport list", tools: ["resolve_group", "list_group_passports"], prompt: "Ask me which group to check, resolve its name and show its saved passport list. Do not generate or download a report." },
  { title: "Check WhatsApp status", tools: ["list_whatsapp_broadcasts"], prompt: "Show the stored WhatsApp broadcasts and their recorded status. Do not prepare or send any messages." },
  { title: "Read my mailbox records", tools: ["list_email_records"], prompt: "Show the retained mailbox records owned by my account. Do not sync my mailbox or fetch anything from the provider." },
  { title: "Review document rename history", tools: ["list_document_rename_batches"], prompt: "Show the stored document rename batches. Do not fetch files or start a rename." },
  { title: "Read the menu", tools: ["list_menu_records"], prompt: "Show the stored menu plans and entries. Do not generate or change a plan." },
] as const;

export function McpReadExamples({ overview, connections, access, uncertain }: {
  overview: McpOverview; connections: McpConnection[]; access: McpReadAccess | undefined; uncertain: boolean;
}) {
  const inventory = useMcpInventory();
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<unknown>(null);
  const copy = async (title: string, prompt: string) => {
    setCopyError(null);
    try { await navigator.clipboard.writeText(prompt); setCopied(title); }
    catch { setCopyError(new Error("The example could not be copied. Select its text and copy it instead.")); }
  };
  return <section aria-label="Read examples" className="space-y-3">
    <div><h2 className="text-base font-semibold text-slate-950">Try a read in Codex</h2><p className="mt-1 text-sm text-slate-600">Copy a prompt after saving the required section permissions and connecting Codex.</p></div>
    <McpError error={inventory.error} onRetry={() => void inventory.refetch()} />
    <div className="grid gap-3 lg:grid-cols-2">{EXAMPLES.map((example) => {
      const tools = example.tools.map((name) => inventory.data?.tools.find((tool) => tool.name === name));
      const requirements = example.tools.map((name) => access?.sections.flatMap((section) => section.tool_requirements ?? []).find((tool) => tool.name === name));
      const requiredIds = [...new Set(requirements.flatMap((tool) => tool?.required_sections ?? []))];
      const known = requirements.every((tool) => tool && tool.required_sections.length > 0)
        && tools.every((tool) => tool?.capability === "mcp:read" && tool.read_only && tool.deployment_available);
      const allowed = !!access && known && requiredIds.every((id) => access.allowed_read_sections.includes(id))
        && tools.every((tool) => tool?.section_access_allowed !== false && tool?.required_read_sections?.every((id) => access.allowed_read_sections.includes(id)) !== false);
      const ready = !uncertain && !inventory.isError && !inventory.isFetching && overview.deployment_enabled && overview.enabled && !overview.emergency_disabled
        && effectiveMcpCapabilities(overview).includes("mcp:read") && hasPermission(connections, ["mcp:read"]) && allowed;
      const state = uncertain || inventory.isError || inventory.isFetching ? "Check access first" : !known ? "Not available yet" : !allowed ? "Sections not allowed" : !overview.enabled || overview.emergency_disabled ? "Access paused" : !hasPermission(connections, ["mcp:read"]) ? "Connect first" : ready ? "Ready to copy" : "Not available yet";
      return <article aria-label={example.title} key={example.title} className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-950">{example.title}</h3><Badge variant={ready ? "success" : "outline"}>{state}</Badge></div>
        <p className="text-sm leading-6 text-slate-600">{example.prompt}</p>
        {known ? <p className="text-xs text-slate-500">Requires: {requiredIds.map((id) => access?.sections.find((section) => section.id === id)?.label ?? id).join(", ")}</p> : null}
        <Button type="button" size="sm" variant="secondary" disabled={!ready} onClick={() => void copy(example.title, example.prompt)}>{copied === example.title ? "Example copied" : "Copy read prompt"}</Button>
      </article>;
    })}</div>
    <McpError error={copyError} />
  </section>;
}
