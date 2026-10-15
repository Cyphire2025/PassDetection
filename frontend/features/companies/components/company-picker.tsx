"use client";

import { useId, useRef, useState } from "react";
import { Building2, Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDebounce } from "@/hooks/use-debounce";
import { useCompanyLookup } from "../hooks/use-companies";
import type { CompanyReference } from "../types";

/** One bounded page (20 items) plus the selected reference: O(page size) memory. */
export function CompanyPicker({ agencyId, value, onChange, disabled, error, required = false }: {
  agencyId: string | null;
  value: CompanyReference | null;
  onChange: (company: CompanyReference) => void;
  disabled?: boolean;
  error?: string;
  required?: boolean;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string>();
  const [active, setActive] = useState(0);
  const debouncedSearch = useDebounce(search, 250);
  const result = useCompanyLookup(agencyId, { search: debouncedSearch, cursor, page_size: 20 }, open);
  const pending = result.isFetching || search !== debouncedSearch;
  const items = pending || result.isError ? [] : result.data?.items ?? [];
  const activeIndex = Math.min(active, items.length - 1);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  const select = (company: CompanyReference) => { onChange(company); close(); };

  return (
    <div className="min-w-0 space-y-2">
      <label id={`${id}-label`} className="block text-sm font-medium text-slate-700">Company / Client{required ? " *" : ""}</label>
      <button ref={trigger} type="button" aria-labelledby={`${id}-label ${id}-value`} aria-expanded={open} aria-controls={`${id}-panel`}
        aria-describedby={error ? `${id}-error` : `${id}-hint`} disabled={disabled || !agencyId}
        onClick={() => { setOpen(!open); if (!open) requestAnimationFrame(() => searchInput.current?.focus()); }}
        className="flex min-h-11 w-full items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:opacity-50">
        <Building2 className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
        <span id={`${id}-value`} className="min-w-0 flex-1 break-words">{value?.name ?? "Select a company / client"}{value?.status === "inactive" ? " (Inactive)" : ""}</span>
        <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" />
      </button>
      <p id={`${id}-hint`} className="text-xs leading-5 text-slate-500">{value?.status === "inactive" ? "This existing assignment is inactive. Select an active company to change it." : "Search active client companies in your workspace."}</p>
      {open && (
        <div id={`${id}-panel`} className="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <input ref={searchInput} role="combobox" aria-label="Search companies" aria-expanded="true" aria-autocomplete="list"
            aria-controls={`${id}-list`} aria-activedescendant={activeIndex >= 0 ? `${id}-option-${activeIndex}` : undefined}
            autoComplete="off" value={search} maxLength={120} placeholder="Start typing a company name"
            onChange={(event) => { setSearch(event.target.value); setCursor(undefined); setActive(0); }}
            onKeyDown={(event) => {
              if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                setActive(items.length ? (Math.max(0, activeIndex) + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length : 0);
              }
              if (event.key === "Enter") { event.preventDefault(); if (items[activeIndex]) select(items[activeIndex]); }
            }}
            className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600" />
          <div role="status" className="text-xs text-slate-600">{pending ? "Searching companies…" : result.isError ? "Company search could not be loaded." : items.length ? `${items.length} companies on this page` : "No active companies found. Try a different search."}</div>
          {result.isError && <Button type="button" variant="secondary" size="sm" onClick={() => void result.refetch()}>Retry company search</Button>}
          <ul id={`${id}-list`} role="listbox" aria-label="Active companies" className="max-h-56 overflow-y-auto">
            {items.map((company, index) => (
              <li key={company.id} id={`${id}-option-${index}`} role="option" aria-selected={value?.id === company.id}
                onMouseDown={(event) => event.preventDefault()} onClick={() => select(company)} onPointerMove={() => setActive(index)}
                className={`flex min-h-11 cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm ${activeIndex === index ? "bg-blue-100 text-blue-950" : "text-slate-800 hover:bg-white"}`}>
                <span className="break-words">{company.name}</span>{value?.id === company.id && <Check className="h-4 w-4 shrink-0" aria-hidden="true" />}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            {cursor && !result.isError && <Button type="button" size="sm" variant="secondary" disabled={pending} onClick={() => { setCursor(undefined); setActive(0); }}>First results</Button>}
            {!result.isError && result.data?.has_more && <Button type="button" size="sm" variant="secondary" disabled={pending} onClick={() => { setCursor(result.data?.next_cursor ?? undefined); setActive(0); }}>More companies</Button>}
            <Button type="button" size="sm" variant="ghost" onClick={close}>Close search</Button>
          </div>
        </div>
      )}
      {error && <p id={`${id}-error`} role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
  );
}
