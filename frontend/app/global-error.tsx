"use client";

import { useRenderErrorReport } from "@/lib/observability/use-render-error-report";

export default function GlobalError({ error, retry }: { error: Error; retry: () => void }) {
  const reference = useRenderErrorReport(error, "global");
  return <html lang="en"><body><main role="alert">
    <h1>The application could not be loaded</h1>
    <p>Try loading it again. If the problem continues, contact support.</p>
    {reference && <p>Support reference: {reference}</p>}
    <button type="button" onClick={retry}>Try again</button>
  </main></body></html>;
}
