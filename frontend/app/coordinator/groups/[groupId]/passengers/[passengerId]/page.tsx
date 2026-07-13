import type { Metadata } from "next";
import { CoordinatorPassengerDetailPage } from "@/features/tour-operations/components/coordinator-passenger-detail-page";

export const metadata: Metadata = {
  title: "Passenger Details | PassDetection",
};

interface CoordinatorPassengerPageProps {
  params: Promise<{ groupId: string; passengerId: string }>;
}

export default async function CoordinatorPassengerPage({ params }: CoordinatorPassengerPageProps) {
  const { groupId, passengerId } = await params;
  return <CoordinatorPassengerDetailPage groupId={groupId} passengerId={passengerId} />;
}
