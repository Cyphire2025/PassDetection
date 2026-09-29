"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { MCP_CAPABILITIES, type McpArtifact, type McpCapability, type McpOperation } from "../api/mcp.api";
import { useMcpArtifacts, useMcpInventory, useMcpOperations } from "../hooks/use-mcp";
import { McpError, McpPagination } from "./mcp-shared";

function capabilityLabel(value: string) {
  if (value === "original_operation_capability") return "Original workflow permission";
  return Object.hasOwn(MCP_CAPABILITIES, value) ? MCP_CAPABILITIES[value as McpCapability].label : "Permission not declared";
}

function groupLink(path: string) {
  return /^\/passports\/groups\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(path) ? path : null;
}

function fileStatus(item: McpArtifact) {
  if (item.kind === "whatsapp_header") {
    if (item.status === "ready") return "Header image ready";
    if (item.status === "uploading") return "Upload receipt pending";
    if (item.status === "unknown") return "Upload outcome uncertain";
  }
  if (item.status === "ingested") return "Document draft created";
  if (item.status === "ingestion_failed") return "Document import failed";
  if (item.status === "imported") return "Broadcast created";
  if (item.status === "unknown") return "Outcome uncertain";
  return item.status;
}

export function McpWorkflows() {
  const [offset, setOffset] = useState(0);
  const query = useMcpOperations(offset);
  return <section aria-label="Saved MCP workflows" className="space-y-4">
    <div><h2 className="text-base font-semibold text-slate-900">Saved workflows</h2><p className="mt-1 text-sm text-slate-500">Use a workflow’s operation ID to continue checking progress from an authorized connection.</p></div>
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading workflows…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No saved workflows on this page.</p> : null}
    {query.data?.items.map((item) => <WorkflowCard key={item.id} item={item} />)}
    <McpPagination offset={offset} nextOffset={query.data?.next_offset ?? null} onChange={setOffset} disabled={query.isFetching} label="Workflow pages" />
  </section>;
}

function WorkflowCard({ item }: { item: McpOperation }) {
  const communication = item.operation.startsWith("confirm_whatsapp_") || item.operation === "confirm_gc_push"
    || item.stage.startsWith("dispatch") || item.stage === "provider_outcome_unknown";
  return <article aria-label={`Workflow ${item.id}`} className="space-y-3 rounded-xl border border-slate-200 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="break-all text-sm font-semibold text-slate-900">{item.operation.replaceAll("_", " ")}</h3>
      <Badge aria-label={`Operation status: ${item.status}`} variant={item.status === "succeeded" ? "success" : "outline"}>{item.status === "unknown" ? "Outcome uncertain" : item.status}</Badge></div>
    {item.status === "running" || item.status === "queued" ? <progress aria-label="Workflow progress" className="h-2 w-full" max={1} value={Number.isFinite(item.progress) ? Math.max(0, Math.min(1, item.progress)) : 0} /> : null}
    <p aria-label="Workflow stage" className="break-words text-sm text-slate-700"><span className="font-medium">Stage: </span>{item.stage.replaceAll("_", " ") || "Not reported"}</p>
    {communication ? <p className="text-xs leading-5 text-slate-500">Dispatch completion does not confirm delivery. Inspect message receipts for sent, delivered, failed or uncertain outcomes.</p> : null}
    <dl className="grid gap-3 text-xs sm:grid-cols-3">
      {([ ["Operation ID", item.id], ["Workflow ID", item.workflow_id], ["Owning connection ID", item.connection_id] ] as const).map(([label, value]) => <div key={label} className="min-w-0">
        <dt className="text-slate-500">{label}</dt><dd className="mt-1 break-all text-slate-700"><code>{value}</code></dd>
      </div>)}
    </dl>
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
      <p>Updated {formatDateTime(item.updated_at)} · Revision {item.revision}</p>
      {item.completed_at ? <p>Operation completed {formatDateTime(item.completed_at)}</p> : null}
    </div>
    {item.created_entities.length ? <ul className="flex flex-wrap gap-3">{item.created_entities.map((entity) => <li key={`${entity.entity_type}:${entity.entity_id}`} className="break-all text-sm">{groupLink(entity.path) ? <Link href={{ pathname: entity.path }} className="font-medium text-blue-700 hover:underline">Open group</Link> : <span className="text-slate-600">{entity.entity_type}: {entity.entity_id}</span>}</li>)}</ul> : null}
  </article>;
}

export function McpFiles() {
  const [offset, setOffset] = useState(0);
  const query = useMcpArtifacts(offset);
  return <section aria-label="MCP file transfers" className="space-y-4">
    <div><h2 className="text-base font-semibold text-slate-900">File transfers</h2><p className="mt-1 text-sm text-slate-500">Source documents, contact workbooks, message header images and generated files. “Delivered” means the connected client acknowledged a verified download.</p></div>
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading files…</p> : null}
    {query.data?.items.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No file transfers on this page.</p> : null}
    <div className="divide-y divide-slate-200">{query.data?.items.map((item) => <article key={item.id} className="flex flex-wrap items-start justify-between gap-3 py-4">
      <div className="min-w-0"><h3 className="break-all text-sm font-medium text-slate-900">{item.filename}</h3><p className="mt-1 text-xs text-slate-500">{item.kind === "whatsapp_header" ? "WhatsApp header image" : item.kind === "contact_workbook" ? "Contact workbook" : item.direction === "upload" ? "Source document" : "Generated export"} · {item.byte_size.toLocaleString()} bytes</p><p className="mt-1 text-xs text-slate-500">Expires {formatDateTime(item.expires_at)}</p>{item.kind === "whatsapp_header" ? <p className="mt-1 text-xs text-slate-500">Image preparation does not confirm message delivery.</p> : null}</div>
      <Badge variant={item.status === "delivered" ? "success" : "outline"}>{fileStatus(item)}</Badge>
    </article>)}</div>
    <p className="text-xs text-slate-500">Use an authorized connection to retrieve a protected file or inspect its workflow. Staging an upload does not confirm that it was imported.</p>
    <McpPagination offset={offset} nextOffset={query.data?.next_offset ?? null} onChange={setOffset} disabled={query.isFetching} label="File pages" />
  </section>;
}

export function McpToolInventory() {
  const query = useMcpInventory();
  return <section aria-label="Deployed MCP tools" className="space-y-4">
    <div><h2 className="text-base font-semibold text-slate-900">Available tools</h2><p className="mt-1 text-sm text-slate-500">Tools registered in this release. Connection permissions and the emergency switch also control access.</p></div>
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading tool inventory…</p> : null}
    {query.data ? <p className="text-xs text-slate-500">{query.data.tool_count} tools · {query.data.environment} · {query.data.qualification === "qualified" ? "Qualified release" : "Qualification in progress"}</p> : null}
    <div className="grid gap-3 md:grid-cols-2">{query.data?.tools.map((tool) => <article key={tool.name} className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="break-all text-sm font-semibold text-slate-900">{tool.name.replaceAll("_", " ")}</h3><Badge variant={tool.deployment_available ? "outline" : "secondary"}>{tool.deployment_available ? "Enabled in deployment" : "Disabled in deployment"}</Badge></div>
      <p className="mt-2 text-xs text-slate-500">{capabilityLabel(tool.capability)}{tool.read_only ? " · Read only" : ""}</p>
      {tool.description ? <p className="mt-2 text-sm leading-6 text-slate-600">{tool.description.split("\n")[0]}</p> : null}
    </article>)}</div>
    {query.data?.file_transports.length ? <div className="rounded-xl bg-slate-50 p-4"><h3 className="text-sm font-semibold text-slate-900">Protected file transfers</h3><ul className="mt-2 space-y-2 text-sm text-slate-600">{query.data.file_transports.map((item) => <li key={item.name}>{item.name.replaceAll("_", " ")} · {(item.required_capabilities ?? [item.capability]).map(capabilityLabel).join(" + ")}</li>)}</ul></div> : null}
  </section>;
}
