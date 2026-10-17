import type { ReactNode } from "react";
import { BroadcastWorkspaceShell } from "@/features/whatsapp/workspace/broadcast-workspace-shell";

export default async function BroadcastLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ broadcastId: string }>;
}) {
  const { broadcastId } = await params;
  return (
    <BroadcastWorkspaceShell broadcastId={broadcastId}>
      {children}
    </BroadcastWorkspaceShell>
  );
}
