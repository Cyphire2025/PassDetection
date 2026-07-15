import type { Metadata } from "next";
import { ManagedAccountsPanel } from "@/features/operations/components/managed-accounts-panel";

export const metadata: Metadata = {
  title: "Staff | PassDetection",
};

export default function StaffPage() {
  return <ManagedAccountsPanel />;
}
