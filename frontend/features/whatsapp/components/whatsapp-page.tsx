"use client";

import dynamic from "next/dynamic";
import { MessageCircle } from "lucide-react";
import {
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { Skeleton } from "@/components/ui/skeleton";

const WhatsAppWorkspace = dynamic(
  () => import("../workspace/broadcast-index").then((module) => module.BroadcastIndex),
  { loading: () => <WhatsAppWorkspaceLoading /> },
);

export function WhatsAppPage() {
  return <WhatsAppWorkspace />;
}

function WhatsAppWorkspaceLoading() {
  return (
    <div className="flex flex-col gap-5" aria-label="Loading WhatsApp communication centre">
      <WorkspacePageHeader
        title="WhatsApp"
        description="Loading broadcast groups, recipient readiness, delivery history, and approved trip-message controls."
        icon={MessageCircle}
        accent="emerald"
      />
      <Skeleton className="h-14 w-full rounded-xl" />
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  );
}
