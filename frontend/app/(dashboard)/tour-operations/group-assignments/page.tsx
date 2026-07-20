import type { Metadata } from "next";
import { TourGroupAssignmentsPage } from "@/features/operations/components/tour-group-assignments-page";

export const metadata: Metadata = {
  title: "Tour Group Assignments | Global Connects Dashboard",
};

export default function GroupAssignmentsPage() {
  return <TourGroupAssignmentsPage />;
}
