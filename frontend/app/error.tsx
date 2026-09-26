"use client";

import { Button } from "@/components/ui/button";
import { useRenderErrorReport } from "@/lib/observability/use-render-error-report";

export default function RouteError({ error, retry }: { error: Error; retry: () => void }) {
  const reference = useRenderErrorReport(error, "route");
  return <main className="mx-auto max-w-lg space-y-4 p-8" role="alert">
    <h1 className="text-xl font-semibold">This screen could not be loaded</h1>
    <p>Your saved work has not been removed. Try loading the screen again.</p>
    {reference && <p className="text-sm">Support reference: {reference}</p>}
    <Button onClick={retry}>Try again</Button>
  </main>;
}
