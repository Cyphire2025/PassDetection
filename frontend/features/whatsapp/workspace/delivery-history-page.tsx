"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ROUTES } from "@/constants/routes";
import { useBroadcast } from "./broadcast-workspace-shell";
import { MessageTypeOverview } from "./message-type-overview";
import { MessageHistoryList } from "./message-history-list";
import { MessageDeliveryPage } from "./message-delivery-report";

export function BroadcastHistoryPage() {
  const params = useSearchParams();
  const group = useBroadcast();
  const selected = params.get("message");
  const byType = params.get("view") === "types";
  const base = ROUTES.dashboard.whatsappBroadcastHistory(group.id);
  return selected ? (
    <MessageDeliveryPage key={selected} messageId={selected} />
  ) : (
    <div className="space-y-6">
      <nav
        aria-label="Delivery history views"
        className="inline-flex gap-1 rounded-xl border border-slate-200 bg-white p-1"
      >
        <Link
          href={base}
          aria-current={!byType ? "page" : undefined}
          className={`rounded-lg px-4 py-2 text-sm font-medium ${!byType ? "bg-slate-900 text-white" : "text-slate-500 hover:bg-slate-50"}`}
        >
          Every send
        </Link>
        <Link
          href={`${base}?view=types`}
          aria-current={byType ? "page" : undefined}
          className={`rounded-lg px-4 py-2 text-sm font-medium ${byType ? "bg-slate-900 text-white" : "text-slate-500 hover:bg-slate-50"}`}
        >
          By message type
        </Link>
      </nav>
      {byType ? (
        <MessageTypeOverview
          messageType={params.get("type")}
          versions={params.get("report") === "versions"}
        />
      ) : (
        <MessageHistoryList />
      )}
    </div>
  );
}
