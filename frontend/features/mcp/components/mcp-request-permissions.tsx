"use client";

import { useMcpPermissions } from "../hooks/use-mcp";
import { deviceWriteSections, validPermissions } from "../utils/permissions";
import { McpPermissionSwitch } from "./mcp-permission-switch";
import { McpPermissionSections } from "./mcp-permission-sections";
import { McpError } from "./mcp-shared";

export function McpRequestPermissions({ readEnabled, writeEnabled, writeSections, readScope, writeScope, disabled, onRead, onWrite, onSections }: {
  readEnabled: boolean; writeEnabled: boolean; writeSections: string[]; readScope: boolean; writeScope: boolean; disabled: boolean;
  onRead: (enabled: boolean) => void; onWrite: (enabled: boolean) => void; onSections: (sections: string[]) => void;
}) {
  const query = useMcpPermissions();
  const data = query.data && validPermissions(query.data) ? query.data : null;
  const blocked = disabled || query.isFetching || query.isError || !data;
  const sections = data ? deviceWriteSections(data) : [];
  return <section aria-label="New connection allowances" className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/50 p-4">
    <div><h4 className="text-sm font-semibold text-slate-950">Connection allowances</h4><p className="mt-1 text-xs leading-5 text-slate-500">New connections start with write access off. Review the allowances before approving.</p></div>
    <McpError error={query.error} onRetry={() => void query.refetch()} />
    {query.isPending ? <p role="status" className="text-sm text-slate-500">Checking saved section settings…</p> : null}
    <McpPermissionSwitch label="Allow read access" description="Use the read sections allowed in Settings." checked={readEnabled && readScope} disabled={blocked || !readScope} onChange={onRead} />
    <McpPermissionSwitch label="Allow write access" description="Allow the reviewed write sections for this connection." checked={writeEnabled && writeScope} disabled={blocked || !writeScope || !data?.write_available}
      onChange={(enabled) => { onWrite(enabled); if (enabled && !writeSections.length) onSections([...(data?.allowed_write_sections ?? [])]); }} />
    {!writeScope ? <p className="text-xs leading-5 text-slate-600">The selected permissions do not include write actions. A new request is required to approve actions the app did not request.</p> : null}
    {writeEnabled && writeScope && data?.write_available ? <McpPermissionSections mode="write" sections={sections} selected={writeSections} disabled={blocked} onChange={onSections} /> : null}
  </section>;
}
