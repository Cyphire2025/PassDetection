"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function WorkspacePagination({
  total,
  offset,
  limit,
  onChange,
  busy = false,
  label = "Results",
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
  busy?: boolean;
  label?: string;
}) {
  return (
    <nav aria-label={`${label} pagination`}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3">
      <p aria-live="polite" className="text-xs tabular-nums text-slate-500">
        {total === 0 ? "0 results" : `${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}`}
      </p>
      <div className="flex gap-2">
        <Button type="button" variant="ghost" disabled={busy || offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}>
          <ArrowLeft className="h-3.5 w-3.5" />Previous
        </Button>
        <Button type="button" variant="ghost" disabled={busy || offset + limit >= total}
          onClick={() => onChange(offset + limit)}>
          Next<ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </nav>
  );
}
