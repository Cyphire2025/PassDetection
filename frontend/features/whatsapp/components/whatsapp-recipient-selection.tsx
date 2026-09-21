"use client";

import { useEffect, useRef } from "react";

export type RecipientWorkspaceSection = "recipients" | "travellers" | "add" | "details";

export function RecipientWorkspaceNavigation({
  section, onChange, recipientCount, pendingCount, readOnly = false, sourceContactCount,
}: {
  section: RecipientWorkspaceSection;
  onChange: (section: RecipientWorkspaceSection) => void;
  recipientCount: number;
  pendingCount: number;
  readOnly?: boolean;
  sourceContactCount?: number;
}) {
  return (
    <nav aria-label="Broadcast workspace" className="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-200 bg-white px-4 sm:px-7">
      {([
        ["travellers", "Travellers", sourceContactCount ?? null],
        ["recipients", sourceContactCount === undefined ? "Recipients" : "Delivery numbers", recipientCount],
        ["add", "Add recipients", pendingCount || null],
        ["details", "Broadcast details", null],
      ] as const).filter(([id]) => (!readOnly || id !== "add") && (id !== "travellers" || sourceContactCount !== undefined)).map(([id, label, count]) => (
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

