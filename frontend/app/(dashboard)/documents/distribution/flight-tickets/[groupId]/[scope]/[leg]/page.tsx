import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentWorkspace } from "@/features/documents/components/document-workspace";
import {
  getFlightDistributionLane,
  isFlightTicketLeg,
  isFlightTicketScope,
} from "@/features/documents/config/document-distribution-lanes";

export const metadata: Metadata = {
  title: "Group Flight Tickets",
};

interface FlightTicketLanePageProps {
  params: Promise<{ groupId: string; scope: string; leg: string }>;
}

export default async function FlightTicketLanePage({
  params,
}: FlightTicketLanePageProps) {
  const { groupId, scope, leg } = await params;
  if (!isFlightTicketScope(scope) || !isFlightTicketLeg(leg)) notFound();

  const lane = getFlightDistributionLane(scope, leg);
  return (
    <DocumentWorkspace
      key={`${groupId}:${lane.documentType}`}
      groupId={groupId}
      lane={lane}
    />
  );
}
