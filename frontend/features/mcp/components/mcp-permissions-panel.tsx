"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui";
import type { McpPermissions } from "../api/mcp.api";
import { useMcpPermissions, useMcpUpdatePermissions } from "../hooks/use-mcp";
import { permissionUpdate, samePermissionUpdate, validPermissions, writeToolsForSections } from "../utils/permissions";
import { McpError } from "./mcp-shared";
import { McpPermissionSwitch } from "./mcp-permission-switch";
import { McpPermissionSections } from "./mcp-permission-sections";

export function McpPermissionsPanel({ unavailable }: { unavailable: boolean }) {
  const query = useMcpPermissions();
  const valid = query.data && validPermissions(query.data);
  return <section aria-label="MCP permission settings" className="space-y-4">
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Checking saved permissions…</p> : null}
    {query.data && !valid ? <p role="alert" className="text-sm text-amber-800">Saved permissions could not be verified. Refresh before changing access.</p> : null}
    {valid && query.data ? <PermissionsEditor data={query.data} unavailable={unavailable || query.isFetching || query.isError}
      reload={async () => { const current = await query.refetch(); return current.isError ? null : current.data ?? null; }} /> : null}
  </section>;
}

function PermissionsEditor({ data, unavailable, reload }: { data: McpPermissions; unavailable: boolean; reload: () => Promise<McpPermissions | null> }) {
  const [draft, setDraft] = useState(() => permissionUpdate(data));
  const [saved, setSaved] = useState<number | null>(null);
  const [reloading, setReloading] = useState(false);
  const update = useMcpUpdatePermissions();
  const stale = draft.expected_revision !== data.permission_revision;
  const conflict = typeof update.error === "object" && update.error !== null && "status" in update.error && update.error.status === 409;
  const dirty = !samePermissionUpdate(draft, permissionUpdate(data));
  const blocked = unavailable || stale || conflict || reloading || update.isPending;
  const reset = async () => {
    setReloading(true);
    const current = await reload();
    if (current && validPermissions(current)) { setDraft(permissionUpdate(current)); setSaved(null); update.reset(); }
    setReloading(false);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (blocked || !dirty) return;
    try {
      const confirmed = await update.mutateAsync(draft);
      if (validPermissions(confirmed)) { setDraft(permissionUpdate(confirmed)); setSaved(confirmed.permission_revision); }
    } catch { /* The existing client handles MFA; errors retain the unsaved draft. */ }
  };
  return <form onSubmit={submit} className="grid gap-6 xl:grid-cols-2">
    {stale || conflict ? <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 xl:col-span-2">Permissions changed elsewhere. Reload the saved settings and review them before saving again. Your unsaved choices have not been applied.</p> : null}
    {unavailable ? <p role="status" className="text-sm text-slate-600 xl:col-span-2">Checking the current permissions. Saving is unavailable until they can be confirmed.</p> : null}
    <section aria-label="Read settings" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div><h2 className="text-base font-semibold text-slate-950">Read settings</h2><p className="mt-1 text-sm leading-6 text-slate-500">Choose the information MCP connections may look up. Saved read sections are preserved when write access is enabled.</p></div>
      <McpPermissionSwitch label="Allow read access" description="Allow approved connections to read the selected sections." checked={draft.read_enabled} disabled={blocked}
        onChange={(read_enabled) => { setDraft((current) => ({ ...current, read_enabled })); setSaved(null); }} />
      <McpPermissionSections mode="read" sections={data.section_catalog} selected={draft.allowed_read_sections} disabled={blocked}
        onChange={(sections) => { setDraft((current) => ({ ...current, allowed_read_sections: [...sections].sort() })); setSaved(null); }} />
    </section>
    <section aria-label="Write settings" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div><h2 className="text-base font-semibold text-slate-950">Write settings</h2><p className="mt-1 text-sm leading-6 text-slate-500">Choose the actions MCP connections may perform. Each device also needs its own write allowance and approved permissions.</p></div>
      {!data.write_available ? <p role="status" className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">Write actions are unavailable on this deployment. Saved write settings do not grant access.</p> : null}
      <McpPermissionSwitch label="Allow write access" description="Allow approved connections to use the selected write actions." checked={draft.write_enabled} disabled={blocked || !data.write_available}
        onChange={(write_enabled) => { setDraft((current) => ({ ...current, write_enabled })); setSaved(null); }} />
      <McpPermissionSections mode="write" sections={data.section_catalog} selected={draft.allowed_write_sections} disabled={blocked || !data.write_available}
        onChange={(sections) => { setDraft((current) => ({ ...current, allowed_write_sections: [...sections].sort(), allowed_write_tools: writeToolsForSections(data, sections) })); setSaved(null); }} />
      <p className="text-xs leading-5 text-slate-500">Actions that span several sections require every relevant section. Turning write access off keeps your section choices.</p>
    </section>
    <div className="xl:col-span-2"><McpError error={update.error} /></div>
    <div className="sticky bottom-3 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-2"><Button type="submit" disabled={blocked || !dirty} isLoading={update.isPending}>Save permissions</Button>
      <Button type="button" variant="secondary" disabled={update.isPending || reloading} onClick={() => void reset()}>Reload saved settings</Button>
      {saved === data.permission_revision && !blocked ? <p role="status" className="text-sm text-green-800">Permissions saved and confirmed.</p> : null}
      {dirty && !stale && !update.isPending ? <p className="text-xs text-slate-500">Unsaved changes</p> : null}</div>
  </form>;
}
