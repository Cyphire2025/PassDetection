import type { Metadata } from "next";
import { RoomingWorkspacePage } from "@/features/operations/components/rooming-workspace-page";

export const metadata: Metadata = { title: "Rooming Allocation | Global Connects Dashboard" };

export default async function RoomingGroupPage({ params }: { params: Promise<{ groupId: string }> }) {
  const { groupId } = await params;
  return <RoomingWorkspacePage groupId={groupId} />;
}
