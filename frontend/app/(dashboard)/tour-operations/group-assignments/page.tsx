import type { Metadata } from "next";
import { TourGroupAssignmentsPage } from "@/features/operations/components/tour-group-assignments-page";

export const metadata: Metadata = {
  title: "Tour Group Assignments | PassDetection",
};

export default function GroupAssignmentsPage() {
  return <TourGroupAssignmentsPage />;
}
