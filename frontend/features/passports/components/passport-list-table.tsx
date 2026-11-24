"use client";

import { CompanyLogo } from "@/features/branding/components/company-logo";
import { Eye } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import { PassportGroupMobileCard, GroupStatusBadge } from "./passport-group-list-card";
import type { PassportListModel } from "./use-passport-list";

type Props = Pick<
  PassportListModel,
  | "filteredGroups"
  | "selectedGroupSet"
  | "toggleGroup"
>;


export function PassportListTable({ filteredGroups, selectedGroupSet, toggleGroup }: Props) {
  return (
    <>
      <div className="grid gap-3 p-4 lg:hidden">
        {filteredGroups.map((group) => (
          <PassportGroupMobileCard
            key={group.group_id}
            group={group}
            selected={selectedGroupSet.has(group.group_id)}
            onToggle={() => toggleGroup(group.group_id)}
          />
        ))}
      </div>

      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full min-w-[980px] text-left text-sm">
          <caption className="sr-only">Group passport workspace readiness</caption>
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
              <th scope="col" className="px-5 py-3">Group</th>
              <th scope="col" className="px-5 py-3">Trip</th>
              <th scope="col" className="px-5 py-3">Status</th>
              <th scope="col" className="px-5 py-3">Passports</th>
              <th scope="col" className="px-5 py-3">Needs review</th>
              <th scope="col" className="px-5 py-3">Latest intake</th>
              <th scope="col" className="px-5 py-3 text-right">Workspace</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filteredGroups.map((group) => {
              const selected = selectedGroupSet.has(group.group_id);
              return (
                <tr
                  key={group.group_id}
                  className={selected
                    ? "cursor-pointer bg-blue-50/65 outline-none transition-colors hover:bg-blue-50"
                    : "cursor-pointer outline-none transition-colors hover:bg-slate-50/70"
                  }
                  onClick={() => toggleGroup(group.group_id)}
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleGroup(group.group_id)}
                        onClick={(event) => event.stopPropagation()}
                        aria-label={`Select ${group.group_name}`}
                        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                      <CompanyLogo src={group.company_logo_url} name={group.company_name || group.group_name} />
                      <div className="min-w-0">
                        <div className="font-semibold text-slate-950">{group.group_name}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {group.confirmed_count.toLocaleString()} confirmed · {group.failed_count.toLocaleString()} failed
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="font-medium text-slate-800">{group.destination || "Destination not set"}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {group.travel_date || "No Travel/Departure date"}
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <GroupStatusBadge status={group.group_status} />
                  </td>
                  <td className="px-5 py-4 font-medium tabular-nums text-slate-800">
                    {group.total_passports.toLocaleString()}
                  </td>
                  <td className="px-5 py-4">
                    <span className={group.pending_review_count > 0 ? "font-semibold tabular-nums text-amber-700" : "font-medium tabular-nums text-emerald-700"}>
                      {group.pending_review_count.toLocaleString()}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-slate-600">
                    {group.total_passports > 0
                      ? formatDateTime(group.latest_submission_at)
                      : "No uploads yet"}
                  </td>
                  <td className="px-5 py-4 text-right">
                    <IntentPrefetchLink
                      href={ROUTES.dashboard.passportGroup(group.group_id)}
                      onClick={(event) => event.stopPropagation()}
                      className="inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
                    >
                      <Eye className="h-4 w-4" aria-hidden="true" />
                      Open Group
                    </IntentPrefetchLink>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
