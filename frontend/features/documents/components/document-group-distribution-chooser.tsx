"use client";

import { ArrowLeft, ArrowRight, FileCheck2, FileStack, Plane } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";
import { useDocumentGroups } from "../hooks/use-document-distribution";

export function DocumentGroupDistributionChooser({ groupId }: { groupId: string }) {
  const groups = useDocumentGroups();
  const group = groups.data?.find((candidate) => candidate.group_id === groupId);
  const flightAssignments = group
    ? group.flight_ticket_assigned_count +
      group.flight_ticket_arrival_assigned_count +
      group.flight_ticket_domestic_assigned_count +
      group.flight_ticket_domestic_arrival_assigned_count
    : 0;

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title={group ? `${group.group_name} Documents` : "Choose a Document Type"}
        description="Choose Visa or Flight Tickets for this group. Existing ticket uploads remain in the International Onward and Return lanes."
        icon={FileStack}
        accent="cyan"
        context={(
          <>
            <WorkspaceHeaderContext icon={FileCheck2}>
              {(group?.visa_assigned_count ?? 0).toLocaleString()} visa assignments
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={Plane}>
              {flightAssignments.toLocaleString()} flight-ticket assignments
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.documentDistribution}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Distribution Home
          </IntentPrefetchLink>
        )}
      />

      {groups.error && (
        <WorkspaceErrorNotice>
          This group could not be refreshed. You can still choose a document type below.
        </WorkspaceErrorNotice>
      )}

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="group-document-family-heading"
      >
        <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">

          <h2 id="group-document-family-heading" className="mt-0.5 font-semibold text-slate-950">
            Choose a document type
          </h2>
        </div>

        <div className="grid md:grid-cols-2">
          <DocumentFamilyLink
            href={ROUTES.dashboard.documentDistributionVisaGroup(groupId)}
            title="Visa"
            description="Upload, match, review, and distribute visa PDFs."
            count={group?.visa_assigned_count ?? 0}
            icon={FileCheck2}
            bordered
          />
          <DocumentFamilyLink
            href={ROUTES.dashboard.documentDistributionFlightGroup(groupId)}
            title="Flight Tickets"
            description="Choose International or Domestic, then Onward or Return."
            count={flightAssignments}
            icon={Plane}
          />
        </div>
      </section>
    </div>
  );
}

function DocumentFamilyLink({
  href,
  title,
  description,
  count,
  icon: Icon,
  bordered = false,
}: {
  href: string;
  title: string;
  description: string;
  count: number;
  icon: typeof FileCheck2;
  bordered?: boolean;
}) {
  return (
    <article className={bordered ? "border-b border-slate-200 p-5 md:border-b-0 md:border-r" : "p-5"}>
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <h3 className="mt-4 text-lg font-semibold text-slate-950">{title}</h3>
      <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
      <p className="mt-3 text-sm font-semibold text-blue-700">
        {count.toLocaleString()} passenger assignments
      </p>
      <IntentPrefetchLink
        href={href}
        className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700"
      >
        Open {title}
        <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </IntentPrefetchLink>
    </article>
  );
}
