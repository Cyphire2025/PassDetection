"use client";

import Link from "next/link";
import { Settings2, Trash2 } from "lucide-react";
import { Badge, Button, Card, CardContent, buttonVariants } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import { describeAppAvailability } from "../availability";
import type { GcAppGroupControl } from "../types";
import { formatGcDateTime } from "../utils";

export function GroupControlCard({
  group,
  onRemove,
  removalDisabled,
}: {
  group: GcAppGroupControl;
  onRemove?: () => void;
  removalDisabled?: boolean;
}) {
  const availability = describeAppAvailability(group);
  return (
    <Card className={group.access_revoked_at ? "border-red-200" : undefined}>
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-semibold text-slate-900">{group.name}</h3>
              <Badge variant={availability.variant}>{availability.label}</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">{group.destination ?? "Destination not set"} · {group.company?.name ?? "Client not assigned"}</p>
            <p className="mt-2 text-sm text-slate-600">{availability.description}</p>
            <p className="mt-1 text-xs text-slate-500">
              Passport collection: {capitalize(group.lifecycle)} · App access: {group.access_starts_at ? formatGcDateTime(group.access_starts_at) : "Immediate"} – {group.access_expires_at ? formatGcDateTime(group.access_expires_at) : "No expiry"}
            </p>
          </div>
          <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:flex-wrap">
            <Link
              href={ROUTES.dashboard.gcAppGroup(group.id) as never}
              className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "col-span-2 justify-center sm:col-span-1")}
            >
              <Settings2 className="h-4 w-4" aria-hidden="true" />
              Open trip
            </Link>
            {onRemove && <Button type="button" variant="ghost" size="sm"
              className="col-span-2 text-red-700 hover:bg-red-50 hover:text-red-800 sm:col-span-1"
              leftIcon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
              disabled={removalDisabled} onClick={onRemove}>
              Remove from GC App
            </Button>}
          </div>
        </div>
        <dl className="grid gap-3 border-t border-slate-100 pt-4 text-sm sm:grid-cols-3">
          <Metric label="Active mobile users" value={group.active_mobile_users} />
          <Metric label="Synced devices" value={group.synced_device_count} />
          <Metric label="Last successful sync" value={group.last_successful_sync_at ? formatGcDateTime(group.last_successful_sync_at) : "Never"} />
        </dl>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-medium text-slate-800">{value}</dd></div>;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
