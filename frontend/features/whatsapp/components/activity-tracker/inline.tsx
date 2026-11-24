"use client";

import { MessageCircle } from "lucide-react";
import { DocumentDeliveryActivity } from "@/features/documents/components/document-delivery-activity";
import { useWhatsAppActivityTracker } from "./context";
import { WhatsAppActivityRow } from "./row";

export function WhatsAppActivityInline() {
  const { activities, dismissActivity } = useWhatsAppActivityTracker();
  if (activities.length === 0) return null;

  return (
    <section
      className="overflow-hidden rounded-2xl border border-blue-200 bg-white shadow-sm"
      aria-label="Live WhatsApp delivery progress"
    >
      <div className="flex items-center gap-2 border-b border-blue-100 bg-blue-50/80 px-4 py-3">
        <MessageCircle className="h-4 w-4 text-blue-700" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-slate-950">
          Live WhatsApp delivery
        </h2>
        <span className="ml-auto text-xs font-medium text-slate-500">
          {activities.length} {activities.length === 1 ? "activity" : "activities"}
        </span>
      </div>
      <div className="divide-y divide-slate-100">
        {activities.map((activity) => activity.kind === "document" ? (
          <DocumentDeliveryActivity
            key={`${activity.kind}:${activity.activity_id}`}
            activity={activity}
            variant="inline"
            onDismiss={dismissActivity}
          />
        ) : (
          <WhatsAppActivityRow
            key={`${activity.kind}:${activity.activity_id}`}
            activity={activity}
            variant="inline"
            onDismiss={dismissActivity}
          />
        ))}
      </div>
    </section>
  );
}
