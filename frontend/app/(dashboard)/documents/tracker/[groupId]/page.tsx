import type { Metadata } from "next";
import { TrackerWorkspace } from "@/features/travel-tracker/components/tracker-workspace";

export const metadata: Metadata = { title: "Group Visa / Flight Tracker" };

export default async function TravelTrackerGroupPage({ params }: { params: Promise<{ groupId: string }> }) {
  const { groupId } = await params;
  return <TrackerWorkspace groupId={groupId} />;
}
