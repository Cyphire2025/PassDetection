"use client";

import { useId } from "react";

export function CompanyViewTabs<T extends string>({ tabs, value, onChange, label, disabled = false }: {
  tabs: readonly { id: T; label: string }[]; value: T; onChange: (value: T) => void; label: string; disabled?: boolean;
}) {
  const id = useId();
  return <div role="tablist" aria-label={label} className="flex gap-1 border-b border-slate-200">
    {tabs.map((tab, index) => <button key={tab.id} id={`${id}-${tab.id}`} type="button" role="tab" disabled={disabled}
      aria-selected={value === tab.id} tabIndex={value === tab.id ? 0 : -1} onClick={() => onChange(tab.id)}
      onKeyDown={(event) => {
        let next: number;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") next = (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault(); onChange(tabs[next].id); document.getElementById(`${id}-${tabs[next].id}`)?.focus();
      }} className={`min-h-11 min-w-0 flex-1 border-b-2 px-2 py-3 text-xs font-semibold sm:flex-none sm:px-4 sm:text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:opacity-50 ${value === tab.id ? "border-blue-700 text-blue-800" : "border-transparent text-slate-500 hover:text-slate-900"}`}>{tab.label}</button>)}
  </div>;
}
