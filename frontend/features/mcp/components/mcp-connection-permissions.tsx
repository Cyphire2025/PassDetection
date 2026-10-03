"use client";

import { useState, type FormEvent } from "react";
import { Button, Input } from "@/components/ui";
import type { McpConnection } from "../api/mcp.api";
import { useMcpPermissions, useMcpRefresh, useMcpUpdateConnection, useMcpUpdateConnectionPermissions } from "../hooks/use-mcp";
import { deviceWriteSections, hasWriteScope, validConnectionPermissions, validPermissions } from "../utils/permissions";
import { McpPermissionSwitch } from "./mcp-permission-switch";
import { McpPermissionSections } from "./mcp-permission-sections";
import { McpError } from "./mcp-shared";

function draftFor(connection: McpConnection) {
  return { expected_revision: connection.permission_revision ?? 0, read_enabled: connection.read_enabled === true,
    write_enabled: connection.write_enabled === true, allowed_read_sections: connection.allowed_read_sections ?? null,
    allowed_write_sections: [...(connection.allowed_write_sections ?? [])] };
}

export function McpConnectionPermissions({ connection, readOnly, unavailable, update, rename, onDone }: {
  connection: McpConnection; readOnly: boolean; unavailable: boolean;
  update: ReturnType<typeof useMcpUpdateConnectionPermissions>; rename: ReturnType<typeof useMcpUpdateConnection>; onDone: () => void;
}) {
  const query = useMcpPermissions();
  const refresh = useMcpRefresh();
  const [name, setName] = useState(connection.name);
  const [draft, setDraft] = useState(() => draftFor(connection));
  const [saved, setSaved] = useState<number | null>(null);
  const data = query.data && validPermissions(query.data) ? query.data : null;
  const valid = validConnectionPermissions(connection);
  const stale = draft.expected_revision !== connection.permission_revision;
  const conflict = typeof update.error === "object" && update.error !== null && "status" in update.error && update.error.status === 409;
  const blocked = unavailable || query.isFetching || query.isError || !data || !valid || stale || conflict || update.isPending || rename.isPending;
  const writeScope = hasWriteScope(connection.capabilities);
  const writeAvailable = !!data?.write_available && !readOnly && writeScope;
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftFor(connection));
  const writeSections = data ? deviceWriteSections(data) : [];
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (blocked || !dirty) return;
    try {
      const confirmed = await update.mutateAsync({ id: connection.id, ...draft });
      if (validConnectionPermissions(confirmed)) { setDraft(draftFor(confirmed)); setSaved(confirmed.permission_revision ?? null); }
    } catch { /* Failed saves keep the local choices; the client handles MFA. */ }
  };
  const reload = async () => {
    await refresh();
    // A fresh editor is opened from the confirmed connection response.
    onDone();
  };
  return <section aria-label="Device permission settings" className="mt-5 space-y-5 border-t border-slate-200 pt-5">
    <form className="flex flex-col items-start gap-3 sm:flex-row sm:items-end" onSubmit={(event) => {
      event.preventDefault();
      if (!unavailable && !rename.isPending && name.trim() && name.trim() !== connection.name)
        rename.mutate({ id: connection.id, name: name.trim(), capabilities: connection.capabilities });
    }}>
      <div className="w-full min-w-0 sm:flex-1"><Input label="Connection name" value={name} maxLength={120} required disabled={unavailable || update.isPending || rename.isPending} onChange={(event) => setName(event.target.value)} /></div>
      <Button type="submit" variant="secondary" disabled={unavailable || update.isPending || !name.trim() || name.trim() === connection.name} isLoading={rename.isPending}>Save name</Button>
    </form>
    <McpError error={rename.error} /><McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Checking current section settings…</p> : null}
    {!valid || (query.data && !data) ? <p role="alert" className="text-sm text-amber-800">Device permissions could not be verified. Refresh before changing access.</p> : null}
    {stale || conflict ? <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This connection&apos;s permissions changed or need a new approval. Reload the connection and review the current access before saving.</p> : null}
    <form onSubmit={submit} className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4"><h4 className="mb-3 text-sm font-semibold text-slate-950">Read allowance</h4>
        <McpPermissionSwitch label="Allow read access" checked={draft.read_enabled} disabled={blocked || !connection.capabilities.includes("mcp:read")}
          description={connection.allowed_read_sections === null ? "Use the read sections enabled in Settings." : "Use this device’s selected read sections, limited by Settings."}
          onChange={(read_enabled) => { setDraft((current) => ({ ...current, read_enabled })); setSaved(null); }} />
        {!connection.capabilities.includes("mcp:read") ? <p className="mt-3 text-xs text-slate-600">Read access requires a new connection request and approval.</p> : null}
        {data && !data.read_enabled ? <p className="mt-3 text-xs text-amber-800">Read access is paused in Settings. Saving a device allowance does not lift that pause.</p> : null}
      </div>
      <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/50 p-4"><h4 className="text-sm font-semibold text-slate-950">Write allowance</h4>
        <McpPermissionSwitch label="Allow write access" checked={draft.write_enabled} disabled={blocked || !writeAvailable}
          description="Permit only the write sections selected below, limited by Settings and this connection’s approved permissions."
          onChange={(write_enabled) => { setDraft((current) => ({ ...current, write_enabled, allowed_write_sections: write_enabled && !current.allowed_write_sections.length ? [...(data?.allowed_write_sections ?? [])] : current.allowed_write_sections })); setSaved(null); }} />
        {!writeScope ? <p className="text-xs leading-5 text-slate-600">This connection was approved without write permissions. Add a new connection request and approve the required actions to allow writes.</p>
          : !writeAvailable ? <p className="text-xs leading-5 text-slate-600">Write actions are unavailable on this deployment.</p> : null}
        {data && writeAvailable ? <McpPermissionSections mode="write" sections={writeSections} selected={draft.allowed_write_sections} disabled={blocked}
          onChange={(allowed_write_sections) => { setDraft((current) => ({ ...current, allowed_write_sections: [...allowed_write_sections].sort() })); setSaved(null); }} /> : null}
        {data && !data.write_enabled ? <p className="text-xs text-amber-800">Write access is paused in Settings. Saving a device allowance does not lift that pause.</p> : null}
      </div>
      <McpError error={update.error} />
      <div className="flex flex-wrap items-center justify-end gap-2"><Button type="button" variant="secondary" disabled={update.isPending || rename.isPending} onClick={onDone}>Close</Button>
        {stale || conflict ? <Button type="button" variant="secondary" disabled={update.isPending || rename.isPending} onClick={() => void reload()}>Reload connection</Button> : null}
        <Button type="submit" disabled={blocked || !dirty} isLoading={update.isPending}>Save access</Button></div>
      {saved === connection.permission_revision && !blocked ? <p role="status" className="text-sm text-green-800">Device permissions saved and confirmed.</p> : null}
    </form>
  </section>;
}
