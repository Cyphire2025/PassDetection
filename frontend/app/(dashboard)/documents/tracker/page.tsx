import type { Metadata } from "next";
import { TrackerGroupList } from "@/features/travel-tracker/components/tracker-group-list";

export const metadata: Metadata = { title: "Visa / Flight Tracker" };

export default function TravelTrackerPage() {
  return <TrackerGroupList />;
}
