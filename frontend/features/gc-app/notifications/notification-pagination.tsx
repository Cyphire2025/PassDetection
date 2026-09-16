"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui";

export function useCursorPage() {
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  return {
    cursor: cursors[cursors.length - 1] ?? null,
    page: cursors.length,
    previous: () => setCursors((values) => values.length > 1 ? values.slice(0, -1) : values),
    next: (cursor: string) => setCursors((values) => values.at(-1) === cursor ? values : [...values, cursor]),
  };
}

export function CursorPagination({ page, nextCursor, disabled, previous, next, onRefresh, itemCount }: {
  page: number;
  nextCursor: string | null;
  disabled: boolean;
  previous: () => void;
  next: (cursor: string) => void;
  onRefresh: () => void;
  itemCount?: number;
}) {
  return <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 text-xs text-slate-500">
    <p aria-live="polite">Page {page}{itemCount !== undefined ? ` · ${itemCount} ${itemCount === 1 ? "record" : "records"} on this page` : ""}</p>
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={onRefresh} leftIcon={<RefreshCw className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}>Refresh</Button>
      <Button type="button" variant="secondary" size="sm" disabled={disabled || page === 1} onClick={previous} leftIcon={<ChevronLeft className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}>Previous</Button>
      <Button type="button" variant="secondary" size="sm" disabled={disabled || !nextCursor} onClick={() => { if (nextCursor) next(nextCursor); }} rightIcon={<ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}>Next</Button>
    </div>
  </div>;
}
