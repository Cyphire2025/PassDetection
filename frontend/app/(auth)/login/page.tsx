/**
 * Login Page
 * ==========
 * Auth feature — login form is in features/auth/components/.
 * This page is a thin shell that renders the feature component.
 */

import type { Metadata } from "next";
import { LoginForm } from "@/features/auth/components/login-form";

export const metadata: Metadata = {
  title: "Sign In | Global Connects Dashboard",
};

export default function LoginPage() {
  return <LoginForm />;
}
