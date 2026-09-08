/**
 * Login Page
 * ==========
 * Auth feature — login form is in features/auth/components/.
 * This page is a thin shell that renders the feature component.
 */

import type { Metadata } from "next";
import { LoginSessionEntry } from "@/features/auth/components/login-session-entry";

export const metadata: Metadata = {
  title: "Sign In | Global Connects Dashboard",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string; from?: string }>;
}) {
  const { reason, from } = await searchParams;
  const notice = reason === "password_changed"
    ? "Password changed. Every previous session was revoked; sign in again with your new password."
    : undefined;
  return <LoginSessionEntry notice={notice} from={from} />;
}
