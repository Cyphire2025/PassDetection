"use client";

import dynamic from "next/dynamic";
import { MessageCircle } from "lucide-react";
import {
  WorkspacePageHeader,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Skeleton } from "@/components/ui/skeleton";

const WhatsAppWorkspace = dynamic(
  () => import("./whatsapp-workspace").then((module) => module.WhatsAppPage),
  { loading: () => <WhatsAppWorkspaceLoading /> },
);

export function WhatsAppPage() {
  return <WhatsAppWorkspace />;
}

function WhatsAppWorkspaceLoading() {
  return (
    <div className="flex flex-col gap-5" aria-label="Loading WhatsApp communication centre">
      <WorkspacePageHeader
        eyebrow="Passenger communication centre"
        title="WhatsApp"
        description="Loading broadcast groups, recipient readiness, delivery history, and approved trip-message controls."
        icon={MessageCircle}
        accent="emerald"
      />
      <WorkspaceSummaryStrip label="Loading WhatsApp operating summary">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[72px] rounded-none" />
        ))}
      </WorkspaceSummaryStrip>
      <Skeleton className="h-14 w-full rounded-xl" />
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  );
}
