"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Input } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import { formatDateTime } from "@/lib/utils/format";
import { MCP_CAPABILITIES, type McpCapability, type McpConnection } from "../api/mcp.api";
import { useMcpRevoke, useMcpSetConnectionAccess, useMcpUpdateConnection } from "../hooks/use-mcp";
import { McpCapabilityPicker, McpError } from "./mcp-shared";

export function McpConnectionCard({ connection, advanced = false, readOnly = true, unavailable = false }: { connection: McpConnection; advanced?: boolean; readOnly?: boolean; unavailable?: boolean }) {
  const [editing, setEditing] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const revoke = useMcpRevoke();
  const access = useMcpSetConnectionAccess();
  const active = connection.status === "active" && connection.enabled !== false;
  const retained = connection.status === "active" || connection.status === "disabled";
  const capabilities = connection.capabilities.filter((scope) => !readOnly || scope === "mcp:read");
  return <article aria-label={connection.name} className="p-5">
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-center lg:gap-5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2"><h3 className="break-words text-sm font-semibold text-slate-950">{connection.name}</h3>
          <Badge variant={active ? "success" : "outline"}>{active ? "Authorized" : retained ? "Disabled" : connection.status === "expired" ? "Sign-in expired" : "Disconnected"}</Badge></div>
        <p className="mt-1 text-xs text-slate-500">{connection.device_platform ?? "Platform not specified"}</p>
        {advanced ? <p className="mt-1 break-all text-xs text-slate-500">{connection.client_id} · {connection.id}</p> : null}
      </div>
      <div className="text-xs"><p className="text-slate-500 lg:sr-only">Last used</p><p className="mt-1 text-slate-700">{connection.last_used_at ? formatDateTime(connection.last_used_at) : "Not used yet"}</p></div>
      <div className="text-xs"><p className="text-slate-500 lg:sr-only">Sign in again by</p><p className="mt-1 text-slate-700">{formatDateTime(connection.expires_at)}</p></div>
      {retained ? <div className="flex min-w-28 flex-wrap items-center gap-1 lg:justify-end">
        {!advanced ? <Button variant={active ? "secondary" : "primary"} size="sm" disabled={unavailable || access.isPending} isLoading={access.isPending}
          onClick={() => { access.reset(); access.mutate({ id: connection.id, enabled: !active }); }}>{active ? "Disable" : "Enable"}</Button> : null}
        <Button variant="ghost" size="sm" disabled={unavailable || access.isPending} aria-expanded={editing} onClick={() => setEditing(!editing)}>{advanced ? "Edit access" : "Manage"}</Button>
        {advanced ? <Button variant="ghost" size="sm" disabled={unavailable} className="text-red-700 hover:text-red-800" onClick={() => { revoke.reset(); setRevoking(true); }}>Disconnect</Button> : null}
      </div> : null}
    </div>
    {advanced ? <dl className="mt-4 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
      {[ ...(advanced ? [["Created", formatDateTime(connection.created_at)]] : []), ["Last used", connection.last_used_at ? formatDateTime(connection.last_used_at) : "Not used yet"],
        ["Sign in again by", formatDateTime(connection.expires_at)] ].map(([label, value]) => <div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-1 text-slate-800">{value}</dd></div>)}
    </dl> : null}
    {advanced ? <div className="mt-4 flex flex-wrap gap-1.5">{capabilities.map((scope) => <Badge key={scope} variant="outline">{MCP_CAPABILITIES[scope]?.label ?? scope}</Badge>)}</div> : null}
    {readOnly && !capabilities.length ? <p className="mt-3 text-xs text-slate-600">This saved connection has no read permission. Sign in again to request read access.</p> : null}
    {editing && retained ? <ConnectionEditor key={`${connection.id}:${connection.name}:${capabilities.join(",")}:${readOnly}`} connection={connection} available={capabilities} unavailable={unavailable} readOnly={readOnly} onDone={() => setEditing(false)} /> : null}
    {editing && retained && !advanced ? <div className="mt-4 border-t border-slate-100 pt-4"><Button variant="ghost" size="sm" disabled={unavailable} className="text-red-700 hover:text-red-800" onClick={() => { revoke.reset(); setRevoking(true); }}>Disconnect permanently</Button><p className="mt-1 text-xs text-slate-500">A disconnected device must request approval again.</p></div> : null}
    <McpError error={access.error} />
    <McpError error={revoke.error} />
    <ConfirmDialog isOpen={revoking} title={`Disconnect ${connection.name}?`} description="This saved connection will immediately lose access. To use it again, sign in and approve access again. Your application records are retained."
      confirmLabel="Disconnect connection" variant="danger" isLoading={revoke.isPending} onClose={() => setRevoking(false)}
      onConfirm={() => revoke.mutate(connection.id, { onSuccess: () => setRevoking(false), onError: () => setRevoking(false) })} />
  </article>;
}

function ConnectionEditor({ connection, available, unavailable, readOnly, onDone }: { connection: McpConnection; available: McpCapability[]; unavailable: boolean; readOnly: boolean; onDone: () => void }) {
  const [name, setName] = useState(connection.name);
  const [capabilities, setCapabilities] = useState<McpCapability[]>(available);
  const update = useMcpUpdateConnection();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !capabilities.length || update.isPending || unavailable) return;
    update.mutate({ id: connection.id, name: name.trim(), capabilities: capabilities.filter((scope) => available.includes(scope)) }, { onSuccess: onDone });
  };
  return <form onSubmit={submit} className="mt-5 space-y-4 border-t border-slate-200 pt-4">
    <Input label="Connection name" value={name} maxLength={120} required disabled={update.isPending} onChange={(event) => setName(event.target.value)} />
    <McpCapabilityPicker available={available} selected={capabilities} onChange={setCapabilities} disabled={update.isPending || unavailable} />
    <p className="text-xs leading-5 text-slate-500">{readOnly ? "Only read access is available on this deployment. Section settings also apply to this connection." : "Changes take effect immediately. Reconnect to authorize additional permissions."}</p>
    <McpError error={update.error} />
    <div className="flex justify-end gap-2"><Button type="button" variant="secondary" disabled={update.isPending} onClick={onDone}>Cancel</Button>
      <Button type="submit" disabled={unavailable || !name.trim() || !capabilities.length} isLoading={update.isPending}>Save access</Button></div>
  </form>;
}
