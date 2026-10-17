import { Button } from "@/components/ui/button";

export function CompanyLoading() {
  return <div role="status" aria-label="Loading company information" className="space-y-3 p-4">{[1, 2, 3].map((row) => <div key={row} className="h-20 rounded-xl bg-slate-100 motion-safe:animate-pulse" />)}<span className="sr-only">Loading company information…</span></div>;
}

export function CompanyError({ message, retry }: { message: string; retry?: () => void }) {
  return <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"><span className="min-w-0 flex-1">{message}</span>{retry && <Button type="button" variant="secondary" size="sm" onClick={retry}>Retry</Button>}</div>;
}

export function CompanyPagination({ hasMore, nextCursor, cursor, pending, onChange }: {
  hasMore: boolean;
  nextCursor: string | null;
  cursor?: string;
  pending: boolean;
  onChange: (cursor: string | undefined) => void;
}) {
  return <nav aria-label="Result pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3">
    <p className="text-xs text-slate-500">Showing a bounded page of results</p>
    <div className="flex gap-2"><Button type="button" variant="secondary" size="sm" disabled={!cursor || pending} onClick={() => onChange(undefined)}>First page</Button><Button type="button" variant="secondary" size="sm" disabled={!hasMore || !nextCursor || pending} onClick={() => onChange(nextCursor ?? undefined)}>Next page</Button></div>
  </nav>;
}

export function companyErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "object" && error !== null && "message" in error && typeof error.message === "string") return error.message;
  return fallback;
}
