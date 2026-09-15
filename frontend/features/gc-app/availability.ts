import type { GcAppAvailability, GcAppAvailabilityReason, GcGroupReference } from "./types";

export const APP_AVAILABILITY_OPTIONS: { value: GcAppAvailability | "all"; label: string }[] = [
  { value: "all", label: "All app states" },
  { value: "active", label: "Available now" },
  { value: "scheduled", label: "Starts later" },
  { value: "paused", label: "Paused" },
  { value: "ended", label: "Access ended" },
  { value: "unavailable", label: "Unavailable" },
];

const REASONS: Record<GcAppAvailabilityReason, string> = {
  group_deleted: "This passport group has been deleted. GC App access is unavailable.",
  group_archived: "This passport group is archived. Restore the group before enabling GC App access.",
  group_unavailable: "This passport group is unavailable. Check the group in the passport workspace.",
  not_configured: "Add this group to GC App and choose its company/client first.",
  app_disabled: "App access is paused. Enable it to use the saved role permissions and access dates.",
  access_revoked: "App access was revoked. Restore it to use the saved role permissions and access dates.",
  no_roles_enabled: "No roles have access. Enable at least one role in Access & features.",
  access_ended: "The app-access window has ended. Review its expiry in Access & features.",
  access_not_started: "App access begins at the saved start date and time.",
};

export function describeAppAvailability(group: GcGroupReference) {
  const status = group.app_availability;
  const label = APP_AVAILABILITY_OPTIONS.find((item) => item.value === status)?.label ?? "Status unavailable";
  const description = group.app_availability_reason
    ? REASONS[group.app_availability_reason]
    : status === "active"
      ? "Eligible users with an enabled role can access this trip in GC App."
      : "Refresh to check the current app availability.";
  const variant = status === "active" ? "success" : status === "unavailable" ? "destructive"
    : status === "paused" || status === "ended" ? "warning" : "outline";
  return { label, description, variant } as const;
}
