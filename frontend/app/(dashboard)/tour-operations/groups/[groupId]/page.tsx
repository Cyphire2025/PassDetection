import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ROUTES } from "@/constants/routes";
import { TourGroupPassengerAssignmentPage } from "@/features/operations/components/tour-group-passenger-assignment-page";
import { PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED } from "@/features/operations/config/tour-operations-flags";

export const metadata: Metadata = {
  title: "Tour Group | Global Connects Dashboard",
};

interface TourGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function TourGroupPage({ params }: TourGroupPageProps) {
  const { groupId } = await params;
  if (!PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED) {
    redirect(ROUTES.dashboard.tourOperationsGroupAssignments);
  }
  // Compatibility-only route retained for rollback. The false flag above
  // keeps passenger-by-passenger allocation inaccessible.
  return <TourGroupPassengerAssignmentPage groupId={groupId} />;
}
