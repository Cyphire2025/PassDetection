import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function TrackerPagination({ page, pageSize, total, busy, onChange }: {
  page: number; pageSize: number; total: number; busy: boolean; onChange: (page: number) => void;
}) {
  if (total <= pageSize) return null;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label="Results pagination" className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3">
      <span className="text-xs text-slate-500">{((page - 1) * pageSize + 1).toLocaleString()}–{Math.min(page * pageSize, total).toLocaleString()} of {total.toLocaleString()}</span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={page === 1 || busy} onClick={() => onChange(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="text-xs font-medium tabular-nums text-slate-600">{page} / {pages}</span>
        <Button variant="secondary" size="sm" disabled={page >= pages || busy} onClick={() => onChange(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </nav>
  );
}
