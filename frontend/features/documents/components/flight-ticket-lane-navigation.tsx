import { ArrowRight, Globe2, MapPin, PlaneLanding, PlaneTakeoff } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { ROUTES } from "@/constants/routes";
import type { DocumentDistributionGroup } from "@/types/document-distribution.types";
import {
  DOCUMENT_DISTRIBUTION_LANES,
  getAssignedCount,
  type DocumentDistributionLane,
  type FlightTicketLeg,
  type FlightTicketScope,
} from "../config/document-distribution-lanes";

const SCOPES: Array<{
  value: FlightTicketScope;
  title: string;
  description: string;
  icon: typeof Globe2;
}> = [
  {
    value: "international",
    title: "International",
    description: "All existing Onward and Return ticket uploads remain here.",
    icon: Globe2,
  },
  {
    value: "domestic",
    title: "Domestic",
    description: "A separate workspace for domestic ticket uploads.",
    icon: MapPin,
  },
];

const LEGS: Array<{
  value: FlightTicketLeg;
  title: string;
  description: string;
  icon: typeof PlaneTakeoff;
}> = [
  {
    value: "onward",
    title: "Onward",
    description: "Outbound journey tickets",
    icon: PlaneTakeoff,
  },
  {
    value: "return",
    title: "Return",
    description: "Return journey tickets",
    icon: PlaneLanding,
  },
];

export function FlightTicketLaneNavigation({
  groupId,
  group,
  lane,
  operationPending,
  hasUncommittedSelection,
}: {
  groupId: string;
  group: DocumentDistributionGroup | undefined;
  lane: DocumentDistributionLane;
  operationPending: boolean;
  hasUncommittedSelection: boolean;
}) {
  if (!lane.scope || !lane.leg) return null;
  const activeScope = lane.scope;
  const activeLeg = lane.leg;
  const canChangeLane = (active: boolean) =>
    !operationPending &&
    (active ||
      !hasUncommittedSelection ||
      window.confirm(
        "Discard the selected and checked PDFs before changing ticket sections?",
      ));

  return (
    <section
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      aria-labelledby="flight-ticket-workspace-heading"
    >
      <div className="border-b border-slate-200 px-4 py-3.5 sm:px-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
          Flight-ticket workspace
        </p>
        <h2 id="flight-ticket-workspace-heading" className="mt-0.5 font-semibold text-slate-950">
          Choose journey type and direction
        </h2>
      </div>

      <div className="grid border-b border-slate-200 md:grid-cols-2">
        {SCOPES.map((scope, index) => {
          const active = activeScope === scope.value;
          const Icon = scope.icon;
          const targetLane = scope.value === "international"
            ? activeLeg === "onward"
              ? DOCUMENT_DISTRIBUTION_LANES.international_onward
              : DOCUMENT_DISTRIBUTION_LANES.international_return
            : activeLeg === "onward"
              ? DOCUMENT_DISTRIBUTION_LANES.domestic_onward
              : DOCUMENT_DISTRIBUTION_LANES.domestic_return;
          return (
            <IntentPrefetchLink
              key={scope.value}
              href={ROUTES.dashboard.documentDistributionFlightLane(
                groupId,
                scope.value,
                activeLeg,
              )}
              aria-current={active ? "page" : undefined}
              aria-disabled={operationPending}
              tabIndex={operationPending ? -1 : undefined}
              onClick={(event) => {
                if (!canChangeLane(active)) event.preventDefault();
              }}
              className={`group flex items-start gap-4 p-5 transition ${
                index === 0 ? "border-b border-slate-200 md:border-b-0 md:border-r" : ""
              } ${active ? "bg-blue-50/70" : "hover:bg-slate-50"} ${
                operationPending ? "pointer-events-none opacity-60" : ""
              }`}
            >
              <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
                active ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"
              }`}>
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-3">
                  <span className="font-semibold text-slate-950">{scope.title}</span>
                  <ArrowRight className="h-4 w-4 text-slate-400 transition group-hover:translate-x-0.5" aria-hidden="true" />
                </span>
                <span className="mt-1 block text-sm leading-5 text-slate-600">{scope.description}</span>
                <span className="mt-2 block text-xs font-semibold text-blue-700">
                  {getAssignedCount(group, targetLane).toLocaleString()} {activeLeg === "onward" ? "Onward" : "Return"} assignments
                </span>
              </span>
            </IntentPrefetchLink>
          );
        })}
      </div>

      <div className="grid gap-3 p-4 sm:grid-cols-2">
        {LEGS.map((leg) => {
          const active = activeLeg === leg.value;
          const Icon = leg.icon;
          const targetLane = activeScope === "international"
            ? leg.value === "onward"
              ? DOCUMENT_DISTRIBUTION_LANES.international_onward
              : DOCUMENT_DISTRIBUTION_LANES.international_return
            : leg.value === "onward"
              ? DOCUMENT_DISTRIBUTION_LANES.domestic_onward
              : DOCUMENT_DISTRIBUTION_LANES.domestic_return;
          return (
            <IntentPrefetchLink
              key={leg.value}
              href={ROUTES.dashboard.documentDistributionFlightLane(
                groupId,
                activeScope,
                leg.value,
              )}
              aria-current={active ? "page" : undefined}
              aria-disabled={operationPending}
              tabIndex={operationPending ? -1 : undefined}
              onClick={(event) => {
                if (!canChangeLane(active)) event.preventDefault();
              }}
              className={`flex items-center gap-3 rounded-xl border p-4 transition ${
                active
                  ? "border-blue-400 bg-blue-50 ring-2 ring-blue-100"
                  : "border-slate-200 hover:border-blue-300 hover:bg-blue-50/40"
              } ${operationPending ? "pointer-events-none opacity-60" : ""}`}
            >
              <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${
                active ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-500"
              }`}>
                <Icon className="h-4 w-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold text-slate-900">{leg.title}</span>
                <span className="block text-xs text-slate-500">{leg.description}</span>
              </span>
              <span className="text-sm font-semibold text-blue-700">
                {getAssignedCount(group, targetLane).toLocaleString()}
              </span>
            </IntentPrefetchLink>
          );
        })}
      </div>
    </section>
  );
}
