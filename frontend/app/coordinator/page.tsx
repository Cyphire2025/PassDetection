import type { Metadata } from "next";
import { CoordinatorMobileShell } from "@/features/tour-operations/components/coordinator-mobile-shell";

export const metadata: Metadata = {
  title: "Coordinator | PassDetection",
};

export default function CoordinatorPage() {
  return <CoordinatorMobileShell />;
}
