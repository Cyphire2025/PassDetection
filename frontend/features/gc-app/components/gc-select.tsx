"use client";

import { Check, ChevronDown, Search } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils/cn";

export interface GcSelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export function GcSelect({
  id,
  label,
  value,
  options,
  onChange,
  placeholder = "Select an option",
  disabled = false,
  error,
  hint,
  searchable = false,
  searchValue,
  onSearchChange,
  searchPlaceholder = "Search options",
  loading = false,
  emptyMessage = "No options found",
  className,
}: {
  id?: string;
  label?: string;
  value: string;
  options: readonly GcSelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  error?: string;
  hint?: string;
  searchable?: boolean;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;
  loading?: boolean;
  emptyMessage?: string;
  className?: string;
}) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const listboxId = `${selectId}-listbox`;
  const errorId = `${selectId}-error`;
  const hintId = `${selectId}-hint`;
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [internalSearch, setInternalSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuPosition, setMenuPosition] = useState<{
    left: number;
    top?: number;
    bottom?: number;
    width: number;
  } | null>(null);
  const effectiveSearch = searchValue ?? internalSearch;
  const setSearch = onSearchChange ?? setInternalSearch;
  const selected = options.find((option) => option.value === value);
  const visibleOptions = useMemo(() => {
    if (!searchable || onSearchChange || !effectiveSearch.trim()) return options;
    const normalized = effectiveSearch.trim().toLocaleLowerCase();
    return options.filter((option) => (
      option.label.toLocaleLowerCase().includes(normalized)
      || option.description?.toLocaleLowerCase().includes(normalized)
    ));
  }, [effectiveSearch, onSearchChange, options, searchable]);

  const positionMenu = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const bounds = trigger.getBoundingClientRect();
    const menuHeight = searchable ? 320 : 272;
    const spaceBelow = window.innerHeight - bounds.bottom;
    const openAbove = spaceBelow < menuHeight && bounds.top > spaceBelow;
    setMenuPosition({
      left: Math.max(8, Math.min(bounds.left, window.innerWidth - bounds.width - 8)),
      ...(openAbove
        ? { bottom: Math.max(8, window.innerHeight - bounds.top + 8) }
        : { top: bounds.bottom + 8 }),
      width: bounds.width,
    });
  }, [searchable]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const reposition = () => positionMenu();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, positionMenu]);

  useEffect(() => {
    if (!open) return;
    if (searchable) requestAnimationFrame(() => searchRef.current?.focus());
  }, [open, searchable]);

  const openMenu = () => {
    const selectedIndex = visibleOptions.findIndex((option) => option.value === value && !option.disabled);
    const firstEnabledIndex = visibleOptions.findIndex((option) => !option.disabled);
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : Math.max(0, firstEnabledIndex));
    positionMenu();
    setOpen(true);
  };

  const move = (direction: 1 | -1) => {
    if (visibleOptions.length === 0) return;
    let next = activeIndex;
    for (let attempts = 0; attempts < visibleOptions.length; attempts += 1) {
      next = (next + direction + visibleOptions.length) % visibleOptions.length;
      if (!visibleOptions[next]?.disabled) {
        setActiveIndex(next);
        break;
      }
    }
  };

  const choose = (option: GcSelectOption | undefined) => {
    if (!option || option.disabled) return;
    onChange(option.value);
    setOpen(false);
    if (searchValue === undefined) setInternalSearch("");
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) openMenu();
      else move(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && !open) {
      event.preventDefault();
      openMenu();
      return;
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      choose(visibleOptions[Math.min(activeIndex, Math.max(0, visibleOptions.length - 1))]);
    }
  };

  return (
    <div ref={rootRef} className={cn("relative flex min-w-0 flex-col gap-1.5", className)}>
      {label && <label id={`${selectId}-label`} className="text-sm font-medium text-slate-700">{label}</label>}
      <button
        ref={triggerRef}
        id={selectId}
        type="button"
        role="combobox"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-labelledby={label ? `${selectId}-label ${selectId}` : undefined}
        aria-describedby={[error && errorId, hint && hintId].filter(Boolean).join(" ") || undefined}
        aria-invalid={Boolean(error)}
        disabled={disabled}
        onClick={() => {
          if (open) setOpen(false);
          else openMenu();
        }}
        onKeyDown={handleKeyDown}
        className={cn(
          "group flex h-10 w-full items-center justify-between gap-3 rounded-xl border bg-white px-3 text-left text-sm shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all",
          "hover:border-slate-400 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600/25",
          "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400 disabled:shadow-none",
          error ? "border-red-400" : open ? "border-blue-500 ring-2 ring-blue-600/10" : "border-slate-300",
        )}
      >
        <span className={cn("min-w-0 truncate", selected ? "font-medium text-slate-900" : "text-slate-400")}>
          {selected?.label ?? placeholder}
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-slate-400 transition-transform", open && "rotate-180 text-blue-600")}
          aria-hidden="true"
        />
      </button>

      {open && menuPosition && createPortal(
        <div
          ref={menuRef}
          style={menuPosition}
          className="fixed z-[110] min-w-[14rem] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_18px_45px_-18px_rgba(15,23,42,0.38)]"
        >
          {searchable && (
            <div className="border-b border-slate-100 bg-slate-50/80 p-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <input
                  ref={searchRef}
                  value={effectiveSearch}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setActiveIndex(0);
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder={searchPlaceholder}
                  aria-label={searchPlaceholder}
                  className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-600/10"
                />
              </div>
            </div>
          )}
          <div id={listboxId} role="listbox" aria-labelledby={label ? `${selectId}-label` : undefined} className="max-h-64 overflow-y-auto p-1.5">
            {loading ? (
              <p role="status" className="px-3 py-6 text-center text-sm text-slate-500">Loading options…</p>
            ) : visibleOptions.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-slate-500">{emptyMessage}</p>
            ) : visibleOptions.map((option, index) => {
              const isSelected = option.value === value;
              const isActive = index === activeIndex;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  disabled={option.disabled}
                  onPointerMove={() => setActiveIndex(index)}
                  onClick={() => choose(option)}
                  className={cn(
                    "flex min-h-10 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left outline-none transition-colors",
                    isActive ? "bg-blue-50 text-blue-950" : "text-slate-700",
                    option.disabled && "cursor-not-allowed opacity-45",
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{option.label}</span>
                    {option.description && <span className="mt-0.5 block truncate text-xs text-slate-500">{option.description}</span>}
                  </span>
                  <Check className={cn("h-4 w-4 shrink-0 text-blue-600", !isSelected && "opacity-0")} aria-hidden="true" />
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      )}

      {hint && !error && <p id={hintId} className="text-xs text-slate-500">{hint}</p>}
      {error && <p id={errorId} role="alert" className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
