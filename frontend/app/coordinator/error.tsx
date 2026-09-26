"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui";
import { useRenderErrorReport } from "@/lib/observability/use-render-error-report";

export default function CoordinatorError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  const reference = useRenderErrorReport(error, "route");

  return (
    <div data-coordinator-shell className="grid place-items-center bg-slate-100 p-[max(1rem,env(safe-area-inset-top))] text-slate-950">
      <main className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-5 text-center shadow-sm">
        <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-red-50 text-red-600">
          <AlertTriangle className="h-7 w-7" aria-hidden="true" />
        </span>
        <h1 className="mt-4 text-xl font-bold">Coordinator app needs a refresh</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Your saved attendance queue is not removed. Try loading this screen again.
        </p>
        <Button type="button" className="mt-5 h-12 w-full text-base" onClick={retry}>
          Try again
        </Button>
        {reference && <p className="mt-3 text-xs text-slate-400">Support reference: {reference}</p>}
      </main>
    </div>
  );
}
