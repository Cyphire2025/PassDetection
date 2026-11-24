"use client";

import { CompanyLogo } from "@/features/branding/components/company-logo";
import { FolderOpen, MapPin } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import type { PassportGroupSummary } from "@/types/passport.types";

export function PassportGroupMobileCard({
  group,
  selected,
  onToggle,
}: {
  group: PassportGroupSummary;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <Card
      className={selected ? "rounded-xl border-blue-300 bg-blue-50/50" : "rounded-xl"}
      onClick={onToggle}
      style={{ contentVisibility: "auto", containIntrinsicSize: "0 270px" }}
    >
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 gap-3">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              onClick={(event) => event.stopPropagation()}
              aria-label={`Select ${group.group_name}`}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <CompanyLogo src={group.company_logo_url} name={group.company_name || group.group_name} />
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-slate-950">{group.group_name}</h3>
              <p className="mt-1 text-xs text-slate-500">
                {group.total_passports > 0
                  ? formatDateTime(group.latest_submission_at)
                  : "No uploads yet"}
              </p>
            </div>
          </div>
          <GroupStatusBadge status={group.group_status} />
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-y border-slate-100 py-3 text-sm">
          <InfoPair label="Passports" value={group.total_passports.toLocaleString()} />
          <InfoPair label="Destination" value={group.destination || "Not set"} icon={MapPin} />
          <InfoPair label="Needs review" value={group.pending_review_count.toLocaleString()} />
          <InfoPair label="Confirmed" value={group.confirmed_count.toLocaleString()} />
        </div>

        <IntentPrefetchLink
          href={ROUTES.dashboard.passportGroup(group.group_id)}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white text-sm font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
          onClick={(event) => event.stopPropagation()}
        >
          <FolderOpen className="h-4 w-4" aria-hidden="true" />
          Open Group
        </IntentPrefetchLink>
      </CardContent>
    </Card>
  );
}

function InfoPair({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon?: typeof MapPin;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {Icon && <Icon className="h-3 w-3" aria-hidden="true" />}
        {label}
      </div>
      <div className="mt-1 truncate font-medium text-slate-800">{value}</div>
    </div>
  );
}

export function GroupStatusBadge({ status }: { status: string }) {
  const variant = status === "active" ? "secondary" : status === "closed" ? "outline" : "default";
  return (
    <Badge variant={variant} dot>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}
