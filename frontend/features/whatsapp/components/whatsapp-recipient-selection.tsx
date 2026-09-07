"use client";

import { Check, FileText, MessageCircle, Users } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui";

export type RecipientWorkspaceSection = "recipients" | "add" | "details";

export function RecipientWorkspaceNavigation({
  section, onChange, recipientCount, pendingCount,
}: {
  section: RecipientWorkspaceSection;
  onChange: (section: RecipientWorkspaceSection) => void;
  recipientCount: number;
  pendingCount: number;
}) {
  return (
    <nav aria-label="Broadcast workspace" className="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-200 bg-white px-4 sm:px-7">
      {([
        ["recipients", "Recipients", recipientCount],
        ["add", "Add recipients", pendingCount || null],
        ["details", "Broadcast details", null],
      ] as const).map(([id, label, count]) => (
        <button
          key={id}
          type="button"
          aria-current={section === id ? "page" : undefined}
          className={`inline-flex shrink-0 items-center gap-2 border-b-2 px-3 py-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${section === id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-900"}`}
          onClick={() => onChange(id)}
        >
          {label}
          {count !== null && <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] tabular-nums text-slate-600">{count}</span>}
        </button>
      ))}
    </nav>
  );
}

export function RecipientSelectionCheckbox({ checked, indeterminate = false, label, disabled = false, onChange }: {
  checked: boolean;
  indeterminate?: boolean;
  label: string;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return <input ref={inputRef} type="checkbox" checked={checked} aria-checked={indeterminate ? "mixed" : checked} aria-label={label} disabled={disabled} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 cursor-pointer rounded border-slate-300 accent-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40" />;
}

export function RecipientSelectionPanel({
  selectedCount, hiddenCount, allCount, onSelectAll, onClear, onReview,
  disabled, error, notice,
}: {
  selectedCount: number;
  hiddenCount: number;
  allCount: number;
  onSelectAll: () => void;
  onClear: () => void;
  onReview: (messageType: "welcome" | "passport_link") => void;
  disabled: boolean;
  error: string | null;
  notice: string | null;
}) {
  return (
    <aside aria-label="Selected recipients" className={`${selectedCount ? "hidden xl:block" : ""} rounded-2xl border border-slate-200 bg-white p-5 xl:sticky xl:top-0`}>
      <div className="flex items-center justify-between gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${selectedCount ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-500"}`}>
          {selectedCount ? <Check className="h-5 w-5" /> : <Users className="h-5 w-5" />}
        </div>
        {selectedCount > 0 && <button type="button" disabled={disabled} onClick={onClear} className="rounded px-1 py-1 text-xs font-semibold text-slate-500 hover:text-slate-900 disabled:opacity-50">Clear selection</button>}
      </div>
      <h3 className="mt-4 text-base font-semibold text-slate-900" aria-live="polite">{selectedCount ? `${selectedCount.toLocaleString()} selected` : "Send again, together"}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
        {selectedCount ? "Choose the saved message you want to send again to these recipients." : "Select people from the list to resend their welcome message or passport link in one action."}
      </p>
      {hiddenCount > 0 && <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800" role="status">{hiddenCount.toLocaleString()} selected {hiddenCount === 1 ? "person is" : "people are"} outside this view. They remain included.</p>}
      {selectedCount < allCount && allCount > 0 && <button type="button" disabled={disabled} onClick={onSelectAll} className="mt-3 text-left text-xs font-semibold text-blue-700 hover:underline disabled:opacity-50">Select all {allCount.toLocaleString()} broadcast recipients</button>}
      <div className="mt-5 grid gap-2.5 border-t border-slate-100 pt-5 sm:grid-cols-2 xl:grid-cols-1">
        <Button type="button" variant="secondary" disabled={!selectedCount || disabled} onClick={() => onReview("welcome")} className="justify-start gap-2.5 py-3">
          <MessageCircle className="h-4 w-4 shrink-0" /> Resend welcome
        </Button>
        <Button type="button" variant="secondary" disabled={!selectedCount || disabled} onClick={() => onReview("passport_link")} className="justify-start gap-2.5 py-3">
          <FileText className="h-4 w-4 shrink-0" /> Resend passport link
        </Button>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-slate-400">You will review the recipients before anything is sent.</p>
      {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p>}
    </aside>
  );
}

export function RecipientMobileSelectionBar({ selectedCount, hiddenCount, allCount, onSelectAll, onClear, onReview, disabled }: {
  selectedCount: number;
  hiddenCount: number;
  allCount: number;
  onSelectAll: () => void;
  onClear: () => void;
  onReview: (messageType: "welcome" | "passport_link") => void;
  disabled: boolean;
}) {
  if (!selectedCount) return null;
  return (
    <section aria-label="Selected recipient actions" className="shrink-0 border-t border-blue-100 bg-white px-4 py-3 shadow-[0_-4px_16px_rgba(15,23,42,0.04)] xl:hidden">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="text-xs font-semibold text-slate-800" aria-live="polite">{selectedCount} selected{hiddenCount ? <span className="font-normal text-amber-700"> · {hiddenCount} outside this view</span> : null}</p>
        <button type="button" disabled={disabled} onClick={onClear} className="text-xs font-semibold text-slate-500 disabled:opacity-40">Clear selection</button>
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <Button type="button" variant="secondary" disabled={disabled} onClick={() => onReview("welcome")} className="gap-1.5 px-2 text-xs"><MessageCircle className="h-3.5 w-3.5" />Resend welcome</Button>
        <Button type="button" variant="secondary" disabled={disabled} onClick={() => onReview("passport_link")} className="gap-1.5 px-2 text-xs"><FileText className="h-3.5 w-3.5" />Resend passport link</Button>
      </div>
      {selectedCount < allCount && <button type="button" disabled={disabled} onClick={onSelectAll} className="mt-2.5 text-xs font-semibold text-blue-700 disabled:opacity-40">Select all {allCount} broadcast recipients</button>}
    </section>
  );
}
