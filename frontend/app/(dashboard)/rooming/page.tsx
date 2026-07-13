import type { Metadata } from "next";
import { RoomingGroupsPage } from "@/features/operations/components/rooming-groups-page";

export const metadata: Metadata = { title: "Rooming Lists | PassDetection" };

export default function RoomingPage() {
  return <RoomingGroupsPage />;
}
