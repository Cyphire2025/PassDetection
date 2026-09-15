import { Badge, Button, Card, CardContent } from "@/components/ui";
import { describeAppAvailability } from "../availability";
import type { GcAppGroupControl } from "../types";
import { formatGcDateTime } from "../utils";

export type GroupWorkspaceTab = "overview" | "access" | "documents" | "announcements" | "history";

export function GroupAppOverview({ control, onNavigate }: {
  control: GcAppGroupControl;
  onNavigate: (tab: GroupWorkspaceTab) => void;
}) {
  const availability = describeAppAvailability(control);
  const roles = [
    control.passenger_access_enabled && "Passengers",
    control.client_manager_access_enabled && "Client Managers",
    control.coordinator_access_enabled && "Coordinators",
  ].filter(Boolean).join(", ") || "No roles enabled";
  return (
    <div className="space-y-4">
      <Card><CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900">Trip readiness</h2>
          <Badge variant={availability.variant}>{availability.label}</Badge>
        </div>
        <p className="text-sm text-slate-600">{availability.description}</p>
        <dl className="grid gap-4 text-sm sm:grid-cols-2">
          <Summary label="Company/client" value={control.company?.name ?? "Not assigned"} />
          <Summary label="Allowed roles" value={roles} />
          <Summary label="App access starts" value={control.access_starts_at ? formatGcDateTime(control.access_starts_at) : "Immediate when enabled"} />
          <Summary label="App access ends" value={control.access_expires_at ? formatGcDateTime(control.access_expires_at) : "No expiry"} />
          <Summary label="Passport collection" value={control.lifecycle.charAt(0).toUpperCase() + control.lifecycle.slice(1)} />
          <Summary label="My Photos setting" value={control.my_photos_enabled ? "Enabled for eligible passengers" : "Disabled"} />
        </dl>
        <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">The passport collection link can be open or closed independently of GC App. Individual users still need an eligible record or account assignment.</p>
      </CardContent></Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Task title="1. Set access & features" action="Manage access" description="Enable or pause the app, choose roles, and review access dates and passenger features." onClick={() => onNavigate("access")} />
        <Task title="2. Prepare trip documents" action="Manage documents" description="Upload the itinerary and shared PDFs as drafts. Review and publish each document when ready." onClick={() => onNavigate("documents")} />
        <Task title="3. Publish announcements" action="Write announcement" description="Save drafts, publish now or schedule availability, and inspect notification delivery separately." onClick={() => onNavigate("announcements")} />
        <Task title="Review change history" action="View history" description="Check who changed app access, published content, or revoked access for this trip." onClick={() => onNavigate("history")} />
      </div>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-medium text-slate-900">{value}</dd></div>;
}

function Task({ title, description, action, onClick }: { title: string; description: string; action: string; onClick: () => void }) {
  return <Card><CardContent className="space-y-3 p-5">
    <h3 className="font-semibold text-slate-900">{title}</h3>
    <p className="text-sm text-slate-600">{description}</p>
    <Button type="button" variant="secondary" onClick={onClick}>{action}</Button>
  </CardContent></Card>;
}
