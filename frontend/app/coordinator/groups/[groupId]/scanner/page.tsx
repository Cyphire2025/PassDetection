import type { Metadata } from "next";
import { CoordinatorGroupScanner } from "@/features/tour-operations/components/coordinator-group-scanner";

export const metadata: Metadata = {
  title: "Activity Scanner | PassDetection",
};

interface CoordinatorGroupScannerPageProps {
  params: Promise<{ groupId: string }>;
  searchParams: Promise<{ sessionId?: string }>;
}

export default async function CoordinatorGroupScannerPage({ params, searchParams }: CoordinatorGroupScannerPageProps) {
  const { groupId } = await params;
  const { sessionId } = await searchParams;
  return <CoordinatorGroupScanner groupId={groupId} sessionId={sessionId ?? null} />;
}
