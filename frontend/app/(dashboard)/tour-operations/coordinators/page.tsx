import type { Metadata } from "next";
import { TourCoordinatorsPage } from "@/features/operations/components/tour-coordinators-page";

export const metadata: Metadata = {
  title: "Tour Coordinators | Global Connects Dashboard",
};

export default function CoordinatorsPage() {
  return <TourCoordinatorsPage />;
}
