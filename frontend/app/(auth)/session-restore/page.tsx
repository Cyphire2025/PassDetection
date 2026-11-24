import type { Metadata } from "next";
import { SessionRestorationPage } from "@/features/auth/components/session-restoration-page";
import { safeRestorationDestination } from "@/features/auth/services/restoration-destination";

export const metadata: Metadata = { title: "Restore session" };

export default async function RestoreSession({ searchParams }: {
  searchParams: Promise<{ from?: string }>;
}) {
  const { from } = await searchParams;
  return <SessionRestorationPage destination={safeRestorationDestination(from)} />;
}
