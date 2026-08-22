import type { Metadata } from "next";
import { PasswordRecoveryCompleteForm } from "@/features/auth/components/password-recovery-forms";

export const metadata: Metadata = {
  title: "Recover account",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

export default function RecoverPasswordPage() {
  return <PasswordRecoveryCompleteForm />;
}
