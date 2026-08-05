import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Audit Logs",
};

export default function AuditLogsLayout({ children }: { children: ReactNode }) {
  return children;
}
