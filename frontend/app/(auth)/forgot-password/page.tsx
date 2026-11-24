import type { Metadata } from "next";
import { PasswordRecoveryRequestForm } from "@/features/auth/components/password-recovery-forms";

export const metadata: Metadata = { title: "Reset password" };

export default function ForgotPasswordPage() {
  return <PasswordRecoveryRequestForm />;
}
