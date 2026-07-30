import type { Metadata } from "next";
import type { ReactNode } from "react";
import { EmailIntegrationsShell } from "@/features/email-integrations/components/email-integrations-shell";

export const metadata: Metadata = {
  title: "Travel Operations Inbox",
  description:
    "Review account-scoped email intelligence, approvals, deadlines, drafts, and processing activity.",
};

export default function EmailIntegrationsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <EmailIntegrationsShell>{children}</EmailIntegrationsShell>;
}
