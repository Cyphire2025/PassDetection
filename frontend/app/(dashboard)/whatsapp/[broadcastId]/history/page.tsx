import { BroadcastHistoryPage } from "@/features/whatsapp/workspace/delivery-history-page";
import { Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";

export default function Page() {
  return (
    <Suspense fallback={<Skeleton className="h-72" />}>
      <BroadcastHistoryPage />
    </Suspense>
  );
}
