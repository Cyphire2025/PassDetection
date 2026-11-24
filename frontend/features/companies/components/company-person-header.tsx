import { Pencil, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CompanyPersonRecord } from "../types/company-people";

export function CompanyPersonHeader({ data, editing, busy, onEdit }: {
  data: CompanyPersonRecord | undefined;
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
}) {
  return (
    <header className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-blue-900">
          <UserRound className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h1 className="break-words text-2xl font-semibold tracking-tight text-slate-950">
            {editing ? "Edit current details" : data?.display_name ?? "Person details"}
          </h1>
          <p className="mt-1 text-xs text-slate-500">Current details, submissions and trip groups</p>
        </div>
      </div>
      {data && !editing && <Button
        type="button"
        variant="secondary"
        disabled={busy}
        onClick={onEdit}
      ><Pencil className="h-4 w-4" aria-hidden="true" />Edit details</Button>}
    </header>
  );
}
