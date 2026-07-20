import type { Metadata } from "next";
import { TourGroupAttendancePage } from "@/features/operations/components/tour-group-attendance-page";

export const metadata: Metadata = {
  title: "Tour Attendance | Global Connects Dashboard",
};

interface TourGroupAttendanceRouteProps {
  params: Promise<{ groupId: string }>;
}

export default async function TourGroupAttendanceRoute({ params }: TourGroupAttendanceRouteProps) {
  const { groupId } = await params;
  return <TourGroupAttendancePage groupId={groupId} />;
}
