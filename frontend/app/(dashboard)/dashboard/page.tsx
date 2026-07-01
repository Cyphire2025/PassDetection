/**
 * Dashboard Overview Page
 * =======================
 * Summary metrics — total passports, pending reviews, active links.
 * Feature component is in features/dashboard/components/.
 */

import type { Metadata } from "next";
import { DashboardOverview } from "@/features/dashboard/components/dashboard-overview";

export const metadata: Metadata = {
  title: "Dashboard | PassDetection",
};

export default function DashboardPage() {
  return <DashboardOverview />;
}
