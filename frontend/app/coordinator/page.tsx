import type { Metadata } from "next";
import { CoordinatorMobileShell } from "@/features/tour-operations/components/coordinator-mobile-shell";

export const metadata: Metadata = {
  title: "Coordinator | Global Connects Dashboard",
};

export default function CoordinatorPage() {
  return <CoordinatorMobileShell />;
}
