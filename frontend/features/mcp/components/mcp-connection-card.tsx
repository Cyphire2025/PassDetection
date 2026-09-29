"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Input } from "@/components/ui";
import { ConfirmDialog } from "@/components/ui/modal";
import { formatDateTime } from "@/lib/utils/format";
import { MCP_CAPABILITIES, type McpCapability, type McpConnection } from "../api/mcp.api";
import { useMcpRevoke, useMcpUpdateConnection } from "../hooks/use-mcp";
import { McpCapabilityPicker, McpError } from "./mcp-shared";

export function McpConnectionCard({ connection }: { connection: McpConnection }) {
  const [editing, setEditing] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const revoke = useMcpRevoke();
  const active = connection.status === "active";
  return <article aria-label={connection.name} className="rounded-xl border border-slate-200 p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2"><h3 className="break-words text-sm font-semibold text-slate-950">{connection.name}</h3>
          <Badge variant={active ? "success" : "outline"}>{connection.status}</Badge></div>
        <p className="mt-1 break-all text-xs text-slate-500">{connection.client_id}</p>
      </div>
      {active ? <div className="flex gap-1">
        <Button variant="ghost" size="sm" aria-expanded={editing} onClick={() => setEditing(!editing)}>Edit access</Button>
        <Button variant="ghost" size="sm" className="text-red-700 hover:text-red-800" onClick={() => { revoke.reset(); setRevoking(true); }}>Revoke</Button>
      </div> : null}
    </div>
    <dl className="mt-4 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
      {[ ["Created", formatDateTime(connection.created_at)], ["Last used", connection.last_used_at ? formatDateTime(connection.last_used_at) : "Never"],
        ["Authorization expires", formatDateTime(connection.expires_at)] ].map(([label, value]) => <div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-1 text-slate-800">{value}</dd></div>)}
    </dl>
    <div className="mt-4 flex flex-wrap gap-1.5">{connection.capabilities.map((scope) => <Badge key={scope} variant="outline">{MCP_CAPABILITIES[scope]?.label ?? scope}</Badge>)}</div>
    {editing && active ? <ConnectionEditor key={`${connection.id}:${connection.name}:${connection.capabilities.join(",")}`} connection={connection} onDone={() => setEditing(false)} /> : null}
    <McpError error={revoke.error} />
    <ConfirmDialog isOpen={revoking} title={`Revoke ${connection.name}?`} description="This connection will immediately lose access. Reconnecting requires another superadmin sign-in."
      confirmLabel="Revoke connection" variant="danger" isLoading={revoke.isPending} onClose={() => setRevoking(false)}
      onConfirm={() => revoke.mutate(connection.id, { onSuccess: () => setRevoking(false), onError: () => setRevoking(false) })} />
  </article>;
}

function ConnectionEditor({ connection, onDone }: { connection: McpConnection; onDone: () => void }) {
  const [name, setName] = useState(connection.name);
  const [capabilities, setCapabilities] = useState<McpCapability[]>(connection.capabilities);
  const update = useMcpUpdateConnection();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !capabilities.length || update.isPending) return;
    update.mutate({ id: connection.id, name: name.trim(), capabilities }, { onSuccess: onDone });
  };
  return <form onSubmit={submit} className="mt-5 space-y-4 border-t border-slate-200 pt-4">
    <Input label="Connection name" value={name} maxLength={120} required disabled={update.isPending} onChange={(event) => setName(event.target.value)} />
    <McpCapabilityPicker available={connection.capabilities} selected={capabilities} onChange={setCapabilities} disabled={update.isPending} />
    <p className="text-xs leading-5 text-slate-500">Changes take effect immediately. Reconnect to authorize additional permissions.</p>
    <McpError error={update.error} />
    <div className="flex justify-end gap-2"><Button type="button" variant="secondary" disabled={update.isPending} onClick={onDone}>Cancel</Button>
      <Button type="submit" disabled={!name.trim() || !capabilities.length} isLoading={update.isPending}>Save access</Button></div>
  </form>;
}
