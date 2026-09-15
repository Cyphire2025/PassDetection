"use client";

import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { useDebounce } from "@/hooks/use-debounce";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import { GcAlert, GcPagination } from "../components/gc-app-feedback";
import type { NotificationAudience } from "./notification-types";

export function NotificationAudiencePicker({ agencyId, audience, groupIds, groupNames, disabled, onChange }: {
  agencyId: string;
  audience: NotificationAudience;
  groupIds: string[];
  groupNames: Record<string, string>;
  disabled: boolean;
  onChange: (audience: NotificationAudience, groupIds: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [names, setNames] = useState<Record<string, string>>({});
  const debouncedSearch = useDebounce(search, 300);
  const groups = useQuery({
    queryKey: ["gc-app", agencyId, "notification-audience-groups", debouncedSearch, page],
    queryFn: ({ signal }) => gcAppAdminApi.listGroups(agencyId, {
      page, page_size: 20, search: debouncedSearch, availability: "active",
    }, signal),
    enabled: audience === "selected_groups",
    placeholderData: keepPreviousData,
    retry: false,
  });

  return <fieldset disabled={disabled} className="min-w-0 space-y-3">
    <legend className="mb-2 text-sm font-semibold text-slate-800">Audience</legend>
    <div className="grid gap-3 sm:grid-cols-2">
      <AudienceOption value="all_active_trips" label="All active GC App trips" description="Eligible app users across the active trips you can manage in this agency." checked={audience === "all_active_trips"} onChange={() => onChange("all_active_trips", [])} />
      <AudienceOption value="selected_groups" label="Specific groups" description="Choose one or more active trips. Review the combined audience before sending." checked={audience === "selected_groups"} onChange={() => onChange("selected_groups", groupIds)} />
    </div>
    {audience === "selected_groups" && <div className="space-y-3 rounded-xl border border-slate-200 p-3">
      <Input label="Find active trips" placeholder="Search group name or destination" value={search} leftAddon={<Search className="h-4 w-4" aria-hidden="true" />} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
      {groups.isError && <div className="space-y-2"><GcAlert message="Active trips could not be loaded. Your selections are kept." /><Button type="button" variant="secondary" size="sm" onClick={() => void groups.refetch()}>Retry trip search</Button></div>}
      {groups.isPending && <p role="status" className="text-sm text-slate-500">Loading active trips…</p>}
      {groups.data && <>
        <div className="max-h-64 space-y-1 overflow-y-auto" aria-label="Available active trips">
          {groups.data.items.length === 0 && <p className="p-3 text-sm text-slate-500">No active trips match this search.</p>}
          {groups.data.items.map((group) => <label key={group.id} className="flex cursor-pointer items-start gap-3 rounded-lg p-3 hover:bg-slate-50">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-blue-600" checked={groupIds.includes(group.id)} disabled={disabled || groups.isPlaceholderData || groups.isError} onChange={(event) => {
              setNames((current) => ({ ...current, [group.id]: group.name }));
              onChange(audience, event.target.checked ? [...groupIds, group.id] : groupIds.filter((id) => id !== group.id));
            }} />
            <span className="min-w-0 text-sm"><span className="block break-words font-medium text-slate-900">{group.name}</span><span className="text-xs text-slate-500">{group.destination ?? "Destination not set"} · {group.company?.name ?? "Company not assigned"}</span></span>
          </label>)}
        </div>
        <GcPagination page={page} total={groups.data.total} pageSize={20} hasNext={groups.data.has_next} disabled={disabled || groups.isFetching} onPageChange={setPage} />
      </>}
      <div className="border-t border-slate-100 pt-3">
        <p className="mb-2 text-xs font-medium text-slate-600">{groupIds.length} selected · selections stay when searching or changing pages</p>
        <div className="flex flex-wrap gap-2">{groupIds.map((id, index) => <button key={id} type="button" onClick={() => onChange(audience, groupIds.filter((value) => value !== id))} className="inline-flex max-w-full items-center gap-2 rounded-full bg-blue-50 px-3 py-1.5 text-xs text-blue-800" aria-label={`Remove ${names[id] ?? groupNames[id] ?? `selected trip ${index + 1}`}`}>
          <span className="truncate">{names[id] ?? groupNames[id] ?? `Selected trip ${index + 1}`}</span><X className="h-3 w-3 shrink-0" aria-hidden="true" />
        </button>)}</div>
      </div>
    </div>}
    <p className="text-xs text-slate-500">Only current authorized app users are eligible. The review shows the server&apos;s audience and registered-device counts.</p>
  </fieldset>;
}

function AudienceOption({ value, label, description, checked, onChange }: {
  value: NotificationAudience; label: string; description: string; checked: boolean; onChange: () => void;
}) {
  return <label className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${checked ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"}`}>
    <input type="radio" name="notification-audience" value={value} checked={checked} onChange={onChange} className="mt-1 h-4 w-4 accent-blue-600" />
    <span className="text-sm"><span className="block font-medium text-slate-900">{label}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{description}</span></span>
  </label>;
}
