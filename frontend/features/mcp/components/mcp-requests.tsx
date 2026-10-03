"use client";

import { useState } from "react";
import { Check, Clock3, X } from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import { formatDateTime } from "@/lib/utils/format";
import { MCP_CAPABILITIES, type McpConnectionRequest, type McpDevicePlatform, type McpOverview } from "../api/mcp.api";
import { useMcpApproveRequest, useMcpPermissions, useMcpRejectRequest, useMcpRequests } from "../hooks/use-mcp";
import { effectiveMcpCapabilities } from "../utils/read-only";
import { hasWriteScope, validPermissions } from "../utils/permissions";
import { McpRequestPermissions } from "./mcp-request-permissions";
import { McpCapabilityPicker, McpError, McpPagination } from "./mcp-shared";

export function McpRequests({ overview, unavailable }: { overview: McpOverview; unavailable: boolean }) {
  const [offset, setOffset] = useState(0);
  const query = useMcpRequests(offset);
  const pending = query.data?.items.filter((item) => item.status === "pending") ?? [];
  const decisions = query.data?.items.filter((item) => item.status !== "pending") ?? [];
  return <section aria-label="MCP access requests" className="space-y-5">
    <div><h2 className="text-xl font-semibold tracking-tight text-slate-950">Requests</h2><p className="mt-1 text-sm leading-6 text-slate-600">Approve or reject new connections. The requester keeps their browser tab open while you review.</p></div>
    <div className="rounded-xl border border-blue-100 bg-blue-50 px-5 py-4 text-sm leading-6 text-blue-950">Compare the code below with the code on the requester&apos;s screen before approving. Approved connections will use your Global Connects account and the permissions you select.</div>
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Loading requests...</p> : null}
    {query.data && !pending.length ? <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center"><Clock3 aria-hidden="true" className="mx-auto h-6 w-6 text-slate-400" /><h3 className="mt-3 text-sm font-semibold text-slate-800">No pending requests</h3><p className="mt-1 text-sm text-slate-500">New requests appear here when someone clicks Authenticate in their MCP app.</p></div> : null}
    {pending.map((request) => <RequestRow key={request.id} request={request} overview={overview} unavailable={unavailable || query.isError} />)}
    {decisions.length ? <section aria-label="Recent request decisions" className="overflow-hidden rounded-xl border border-slate-200 bg-white"><h3 className="border-b border-slate-100 px-5 py-4 text-sm font-semibold text-slate-950">Recent decisions</h3><div className="divide-y divide-slate-100">{decisions.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"><div><p className="text-sm font-medium text-slate-800">{item.name}</p><p className="mt-1 text-xs text-slate-500">{item.client_name} · {item.device_platform} · {formatDateTime(item.decided_at ?? item.created_at)}</p></div><Badge variant={item.status === "approved" || (item.status === "finalized" && !!item.connection_id) ? "success" : "outline"}>{item.status === "finalized" ? item.connection_id ? "Connected" : "Rejected" : item.status === "approved" ? "Approved · waiting for app" : item.status === "rejected" ? "Rejected" : "Expired"}</Badge></div>)}</div></section> : null}
    <McpPagination offset={offset} nextOffset={query.data?.next_offset ?? null} onChange={setOffset} disabled={query.isFetching} label="Request pages" />
  </section>;
}

function RequestRow({ request, overview, unavailable }: { request: McpConnectionRequest; overview: McpOverview; unavailable: boolean }) {
  const [reviewing, setReviewing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const approve = useMcpApproveRequest();
  const reject = useMcpRejectRequest();
  const [name, setName] = useState(request.name);
  const [platform, setPlatform] = useState<McpDevicePlatform>(request.device_platform);
  const available = request.requested_capabilities.filter((item) => effectiveMcpCapabilities(overview).includes(item));
  const [capabilities, setCapabilities] = useState(available);
  const permitted = capabilities.filter((item) => available.includes(item));
  const [readEnabled, setReadEnabled] = useState(true);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [writeSections, setWriteSections] = useState<string[]>([]);
  const permissionQuery = useMcpPermissions(reviewing && overview.permission_controls_available === true);
  const policyReady = !overview.permission_controls_available || (!permissionQuery.isFetching && !permissionQuery.isError && !!permissionQuery.data && validPermissions(permissionQuery.data));
  const canApprove = !unavailable && policyReady && overview.enabled && overview.deployment_enabled && !overview.emergency_disabled;
  const busy = approve.isPending || reject.isPending;
  return <article aria-label={request.name} className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"><div><div className="flex flex-wrap items-center gap-2"><h3 className="text-base font-semibold text-slate-950">{request.name}</h3><Badge variant="outline">Pending</Badge></div><p className="mt-1 text-sm text-slate-500">{request.client_name} · {request.device_platform}</p><p className="mt-2 text-xs text-slate-500">Requested {formatDateTime(request.created_at)} · Expires {formatDateTime(request.expires_at)}</p></div>
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3"><p className="text-xs font-medium text-slate-500">Comparison code</p><p className="mt-1 font-mono text-xl font-semibold tracking-widest text-slate-950">{request.comparison_code}</p></div></div>
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4"><p className="text-xs text-slate-500">Requested: {request.requested_capabilities.map((scope) => MCP_CAPABILITIES[scope]?.label ?? scope).join(", ")}</p><div className="flex gap-2"><Button variant="secondary" size="sm" disabled={unavailable || busy} onClick={() => { reject.reset(); setRejecting(true); }}><X className="h-4 w-4" aria-hidden="true" />Reject</Button><Button size="sm" disabled={unavailable || busy || !overview.enabled || !overview.deployment_enabled || overview.emergency_disabled} onClick={() => { approve.reset(); setReviewing(true); }}><Check className="h-4 w-4" aria-hidden="true" />Approve</Button></div></div>
    {reviewing ? <form className="mt-5 space-y-4 border-t border-slate-100 pt-5" onSubmit={(event) => { event.preventDefault(); if (!busy && canApprove && name.trim() && permitted.length) approve.mutate({ id: request.id, name: name.trim(), device_platform: platform, capabilities: permitted,
      ...(overview.permission_controls_available ? { read_enabled: readEnabled && permitted.includes("mcp:read"), write_enabled: writeEnabled && hasWriteScope(permitted), allowed_read_sections: null, allowed_write_sections: [...writeSections].sort() } : {}) }, { onSuccess: () => setReviewing(false) }); }}>
      <div className="grid gap-4 sm:grid-cols-2"><Input label="Device name" value={name} required maxLength={120} disabled={busy} onChange={(event) => setName(event.target.value)} /><label className="space-y-1.5 text-sm font-medium text-slate-700">Platform<select value={platform} disabled={busy} onChange={(event) => setPlatform(event.target.value as McpDevicePlatform)} className="block min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal">{["Windows", "macOS", "Other"].map((item) => <option key={item}>{item}</option>)}</select></label></div>
      <McpCapabilityPicker available={available} selected={permitted} onChange={setCapabilities} disabled={busy || !canApprove} />
      {overview.permission_controls_available ? <McpRequestPermissions readEnabled={readEnabled} writeEnabled={writeEnabled} writeSections={writeSections}
        readScope={permitted.includes("mcp:read")} writeScope={hasWriteScope(permitted)} disabled={busy || !canApprove}
        onRead={setReadEnabled} onWrite={setWriteEnabled} onSections={setWriteSections} /> : null}
      <p className="text-xs leading-5 text-slate-500">Approve only after matching the comparison code. You may need to confirm your identity. The requester will finish connecting in their own browser.</p>
      <McpError error={approve.error} /><div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="secondary" disabled={busy} onClick={() => setReviewing(false)}>Cancel</Button><Button type="submit" disabled={!canApprove || !name.trim() || !permitted.length} isLoading={approve.isPending}>Approve connection</Button></div>
    </form> : null}
    <McpError error={reject.error} />
    <ConfirmDialog isOpen={rejecting} title={`Reject ${request.name}?`} description="The requester will be told that access was declined. This request will not create an approved device."
      confirmLabel="Reject request" variant="danger" isLoading={reject.isPending} onClose={() => setRejecting(false)} onConfirm={() => reject.mutate(request.id, { onSuccess: () => setRejecting(false), onError: () => setRejecting(false) })} />
  </article>;
}
