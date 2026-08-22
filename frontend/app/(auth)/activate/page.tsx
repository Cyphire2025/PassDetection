import type { Metadata } from "next";
import { ActivationForm } from "@/features/auth/components/activation-form";

export const metadata: Metadata = {
  title: "Activate account",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

export default function ActivatePage() {
  return <ActivationForm />;
}
