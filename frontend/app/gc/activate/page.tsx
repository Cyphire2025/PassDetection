import type { Metadata } from "next";
import { ClientManagerActivationFallback } from "@/features/auth/components/client-manager-activation-fallback";

export const metadata: Metadata = {
  title: "Open Group Companion",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

export default function ClientManagerActivationFallbackPage() {
  return <ClientManagerActivationFallback />;
}
