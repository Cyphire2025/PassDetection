import type { Metadata } from "next";
import { TourCoordinatorsPage } from "@/features/operations/components/tour-coordinators-page";

export const metadata: Metadata = {
  title: "Tour Coordinators | PassDetection",
};

export default function CoordinatorsPage() {
  return <TourCoordinatorsPage />;
}
