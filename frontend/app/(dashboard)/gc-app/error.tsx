"use client";

import { Button, Card, CardContent } from "@/components/ui";
import { useRenderErrorReport } from "@/lib/observability/use-render-error-report";

export default function GcAppError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  const reference = useRenderErrorReport(error, "route");
  return (
    <Card>
      <CardContent className="space-y-4 p-6 text-center">
        <h2 className="text-lg font-semibold text-slate-900">GC App could not be loaded</h2>
        <p className="text-sm text-slate-600">No access settings were changed. Retry when the connection is available.</p>
        {reference && <p className="text-xs text-slate-500">Support reference: {reference}</p>}
        <Button type="button" onClick={retry}>Try again</Button>
      </CardContent>
    </Card>
  );
}
