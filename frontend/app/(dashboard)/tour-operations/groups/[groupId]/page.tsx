import type { Metadata } from "next";
import { TourGroupPassengerAssignmentPage } from "@/features/operations/components/tour-group-passenger-assignment-page";

export const metadata: Metadata = {
  title: "Tour Group Passengers | Global Connects Dashboard",
};

interface TourGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function TourGroupPage({ params }: TourGroupPageProps) {
  const { groupId } = await params;
  return <TourGroupPassengerAssignmentPage groupId={groupId} />;
}
