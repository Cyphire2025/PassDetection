import type { Metadata } from "next";
import type { ReactNode } from "react";
import { EmailIntegrationsShell } from "@/features/email-integrations/components/email-integrations-shell";

export const metadata: Metadata = {
  title: "Email Integrations",
  description:
    "Connect business inboxes and review travel document processing activity.",
};

export default function EmailIntegrationsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <EmailIntegrationsShell>{children}</EmailIntegrationsShell>;
}
