import type { Metadata } from "next";
import { CoordinatorGroupActivityPage } from "@/features/tour-operations/components/coordinator-group-activity-page";

export const metadata: Metadata = {
  title: "Coordinator Group | Global Connects Dashboard",
};

interface CoordinatorGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function CoordinatorGroupPage({ params }: CoordinatorGroupPageProps) {
  const { groupId } = await params;
  return <CoordinatorGroupActivityPage groupId={groupId} />;
}
