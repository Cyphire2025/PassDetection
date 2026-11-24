"use client";
import { ArrowLeft, CheckCircle2, FileCheck2, Plane } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspaceHeaderContext, WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";
import { WhatsAppActivityInline } from "@/features/whatsapp/components/whatsapp-activity-tracker";
import { FlightTicketLaneNavigation } from "./document-workspace-bindings";
import type { DocumentWorkspaceController } from "../hooks/use-document-workspace";

export function DocumentWorkspaceHeader({ controller }: { controller: DocumentWorkspaceController }) {
  const {
    groupId, lane, group, documentTypeOperationPending,
    hasUncommittedSelection, reviewCounts, assignedPassengerCount,
  } = controller;
  const LaneIcon = lane.category === "visa" ? FileCheck2 : Plane;
  return <>
      <WorkspacePageHeader
        title={group ? `${group.group_name} Documents` : "Group Documents"}
        description="Upload PDFs, confirm passenger matches, and save the document list before sending."
        icon={LaneIcon}
        accent="cyan"
        context={(
          <>
            <WorkspaceHeaderContext icon={LaneIcon}>
              {lane.workflowLabel} workflow
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={CheckCircle2}>
              {assignedPassengerCount.toLocaleString()} of {(group?.total_passengers ?? reviewCounts.all).toLocaleString()} assigned
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={lane.category === "visa"
              ? ROUTES.dashboard.documentDistributionVisa
              : ROUTES.dashboard.documentDistributionFlightTickets}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {lane.category === "visa" ? "Visa Groups" : "Flight-Ticket Groups"}
          </IntentPrefetchLink>
        )}
      />

      <WhatsAppActivityInline />

      {lane.category === "flight_tickets" && (
        <FlightTicketLaneNavigation
          groupId={groupId}
          group={group}
          lane={lane}
          operationPending={documentTypeOperationPending}
          hasUncommittedSelection={hasUncommittedSelection}
        />
      )}
  </>;
}
