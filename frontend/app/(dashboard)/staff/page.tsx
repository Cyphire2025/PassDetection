import type { Metadata } from "next";
import { ManagedAccountsPanel } from "@/features/operations/components/managed-accounts-panel";

export const metadata: Metadata = {
  title: "Staff | Global Connects Dashboard",
};

export default function StaffPage() {
  return <ManagedAccountsPanel />;
}
