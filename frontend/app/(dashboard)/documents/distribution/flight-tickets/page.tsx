import type { Metadata } from "next";
import { DocumentGroupList } from "@/features/documents/components/document-group-list";

export const metadata: Metadata = {
  title: "Flight-Ticket Distribution Groups",
};

export default function FlightTicketDistributionGroupsPage() {
  return <DocumentGroupList category="flight_tickets" />;
}
