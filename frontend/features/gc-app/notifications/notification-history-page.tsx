"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { buttonVariants } from "@/components/ui";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useGcAppAgencyScope } from "../components/gc-app-agency-scope";
import { GcDialog } from "../components/gc-dialog";
import { NotificationDeliverySummary } from "./notification-delivery-summary";
import { NotificationHistory } from "./notification-history";
import type { NotificationBatch } from "./notification-types";

export function NotificationHistoryPage() {
  const { agencyId } = useGcAppAgencyScope();
  const user = useAuthStore(selectUser);
  if (!agencyId || !user) return null;
  return <NotificationHistoryWorkspace key={`${agencyId}:${user.id}`} agencyId={agencyId} actorId={user.id} />;
}

function NotificationHistoryWorkspace({ agencyId, actorId }: { agencyId: string; actorId: string }) {
  const [selected, setSelected] = useState<NotificationBatch | null>(null);
  return <div className="space-y-5">
    <PageHeader title="Notification history"
      description="Review every send, its original message and audience, and recorded delivery progress. History stays available when a saved notification is deleted."
      actions={<Link href="/gc-app/notifications" className={buttonVariants({ variant: "secondary" })}><ArrowLeft className="h-4 w-4 shrink-0" aria-hidden="true" />Back to notifications</Link>} />
    <NotificationHistory agencyId={agencyId} actorId={actorId} onView={setSelected} />
    {selected && <GcDialog open title="Notification delivery details" description="Recorded results for this send." onClose={() => setSelected(null)} size="xl">
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><h3 className="break-words font-semibold text-slate-900">{selected.title}</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{selected.body}</p></div>
        <NotificationDeliverySummary key={selected.id} agencyId={agencyId} batch={selected} />
      </div>
    </GcDialog>}
  </div>;
}
