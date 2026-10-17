"use client";

import { useSearchParams } from "next/navigation";
import { MessageHistoryList } from "./message-history-list";
import { MessageDeliveryPage } from "./message-delivery-report";

export function BroadcastHistoryPage() {
  const selected = useSearchParams().get("message");
  return selected ? (
    <MessageDeliveryPage key={selected} messageId={selected} />
  ) : (
    <MessageHistoryList />
  );
}
