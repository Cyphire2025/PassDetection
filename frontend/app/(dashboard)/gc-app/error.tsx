"use client";

import { Button, Card, CardContent } from "@/components/ui";

export default function GcAppError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <Card>
      <CardContent className="space-y-4 p-6 text-center">
        <h2 className="text-lg font-semibold text-slate-900">GC App could not be loaded</h2>
        <p className="text-sm text-slate-600">No access settings were changed. Retry when the connection is available.</p>
        <Button type="button" onClick={reset}>Try again</Button>
      </CardContent>
    </Card>
  );
}
