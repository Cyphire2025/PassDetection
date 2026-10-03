"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button } from "@/components/ui";
import type { McpConnection, McpOverview, McpReadAccess } from "../api/mcp.api";
import { useMcpReadAccess, useMcpUpdateReadAccess } from "../hooks/use-mcp";
import { McpError } from "./mcp-shared";

function validReadAccess(value: McpReadAccess) {
  const supported = new Set(value.sections.filter((section) => section.supported).map((section) => section.id));
  return value.read_only_mode === true && Number.isInteger(value.revision) && value.revision >= 1
    && value.allowed_read_sections.every((id) => supported.has(id));
}

function sameSections(left: string[], right: string[]) {
  return left.length === right.length && left.every((id) => right.includes(id));
}

export function McpReadAccessPanel({ overviewUnavailable }: {
  overview: McpOverview; connections: McpConnection[]; uncertain: boolean; overviewUnavailable: boolean;
}) {
  const query = useMcpReadAccess();
  const valid = query.data && validReadAccess(query.data);
  return <>
    <section aria-label="Sidebar read access" className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
      <div><h2 className="text-base font-semibold text-slate-950">Read settings</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">Allow or deny the available reads for each sidebar section. These settings apply to all MCP connections. Your normal website access stays the same.</p></div>
      <McpError error={query.error} onRetry={() => void query.refetch()} />
      {query.isPending ? <p role="status" className="text-sm text-slate-500">Checking saved read settings…</p> : null}
      {query.data && !valid ? <p role="alert" className="text-sm text-amber-800">Current read-only settings could not be verified. Refresh status before changing access.</p> : null}
      {valid && query.data ? <ReadAccessEditor data={query.data} unavailable={query.isError || query.isFetching || overviewUnavailable}
        reload={async () => { const result = await query.refetch(); return result.isError ? null : result.data ?? null; }} /> : null}
    </section>
  </>;
}

function ReadAccessEditor({ data, unavailable, reload }: {
  data: McpReadAccess; unavailable: boolean; reload: () => Promise<McpReadAccess | null>;
}) {
  const [draft, setDraft] = useState(() => ({ revision: data.revision, allowed: [...data.allowed_read_sections] }));
  const [savedRevision, setSavedRevision] = useState<number | null>(null);
  const [reloading, setReloading] = useState(false);
  const update = useMcpUpdateReadAccess();
  const stale = draft.revision !== data.revision;
  const conflict = typeof update.error === "object" && update.error !== null && "status" in update.error && update.error.status === 409;
  const dirty = !sameSections(draft.allowed, data.allowed_read_sections);
  const blocked = unavailable || stale || update.isPending || reloading || conflict;
  const resetFromServer = async () => {
    setReloading(true);
    const current = await reload();
    if (current && validReadAccess(current)) {
      setDraft({ revision: current.revision, allowed: [...current.allowed_read_sections] });
      setSavedRevision(null);
      update.reset();
    }
    setReloading(false);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (blocked || !dirty) return;
    try {
      const confirmed = await update.mutateAsync({ allowed_read_sections: [...draft.allowed].sort(), expected_revision: draft.revision });
      if (validReadAccess(confirmed)) {
        setDraft({ revision: confirmed.revision, allowed: [...confirmed.allowed_read_sections] });
        setSavedRevision(confirmed.revision);
      }
    } catch { /* The mutation displays the server or MFA error below. */ }
  };
  return <form onSubmit={submit} className="space-y-4">
    {stale || conflict ? <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Read settings changed elsewhere. Reload the saved settings and review them before saving again. Your unsaved choices have not been applied.</p> : null}
    {unavailable ? <p role="status" className="text-sm text-slate-600">Checking the current policy failed or is still in progress. Saving is unavailable until it can be confirmed.</p> : null}
    <fieldset disabled={blocked} className="divide-y divide-slate-100 rounded-xl border border-slate-200">
      <legend className="sr-only">Sidebar sections</legend>
      {data.sections.map((section) => <div key={section.id} className="relative px-4 py-4 sm:px-5">
        {section.supported ? <label className="flex cursor-pointer items-center justify-between gap-4">
          <span className="text-sm font-medium text-slate-950">{section.label}</span>
          <input type="checkbox" role="switch" aria-label={`Allow ${section.label}`} aria-describedby={`read-coverage-${section.id}`} className="peer sr-only"
            checked={draft.allowed.includes(section.id)} onChange={(event) => {
              const checked = event.target.checked;
              setDraft((current) => ({ ...current, allowed: checked ? [...current.allowed, section.id] : current.allowed.filter((id) => id !== section.id) }));
              setSavedRevision(null);
            }} />
          <span aria-hidden="true" className="relative h-6 w-11 shrink-0 rounded-full bg-slate-200 transition-colors after:absolute after:left-1 after:top-1 after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:bg-blue-600 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-blue-600 peer-focus-visible:ring-offset-2 peer-disabled:opacity-50" />
        </label> : <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-medium text-slate-950">{section.label}</h3><Badge variant="outline">{section.metadata_only ? "Connection metadata" : "Not available yet"}</Badge></div>}
        <p id={`read-coverage-${section.id}`} className="mt-1 max-w-3xl pr-12 text-xs leading-5 text-slate-500">{section.coverage_description ?? "Only the listed read tools are covered. Additional page features are not available through Codex."}</p>
        {section.supported && section.tool_requirements?.length ? <details className="mt-2 text-xs text-slate-500"><summary className="cursor-pointer">Required sections for these reads</summary>
          <ul className="mt-2 space-y-1">{section.tool_requirements.map((tool) => <li key={tool.name}>{tool.name.replaceAll("_", " ")}: {tool.required_sections.map((id) => data.sections.find((item) => item.id === id)?.label ?? id).join(", ")}</li>)}</ul>
        </details> : null}
      </div>)}
    </fieldset>
    <p className="text-xs leading-5 text-slate-500">A read that includes information from several sections requires all of those sections. Connection status is available independently of business section permissions.</p>
    <McpError error={update.error} />
    <div className="flex flex-wrap items-center gap-3">
      <Button type="submit" disabled={blocked || !dirty} isLoading={update.isPending}>Save read access</Button>
      <Button type="button" variant="secondary" disabled={update.isPending || reloading} onClick={() => void resetFromServer()}>Reload saved settings</Button>
      {savedRevision !== null && savedRevision === data.revision && !unavailable ? <p role="status" className="text-sm text-green-800">Read access saved and confirmed.</p> : null}
      {dirty && !stale && !update.isPending ? <p className="text-xs text-slate-500">Unsaved changes</p> : null}
    </div>
  </form>;
}
