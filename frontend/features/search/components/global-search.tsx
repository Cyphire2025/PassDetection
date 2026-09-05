"use client";

import { ROUTES } from "@/constants/routes";
import { FileText, FolderOpen, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { searchApi, type GlobalSearchResult } from "../api/search.api";

export function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResult[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputId = useId();
  const listboxId = `${inputId}-results`;
  const statusId = `${inputId}-status`;

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    document.addEventListener("keydown", shortcut);
    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", shortcut);
    };
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      return;
    }

    let active = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      searchApi
        .global(trimmed, controller.signal)
        .then((items) => {
          if (!active) return;
          setError(null);
          setResults(items);
          setActiveIndex(items.length > 0 ? 0 : -1);
        })
        .catch(() => {
          if (!active) return;
          setError("Search is temporarily unavailable. Try again.");
          setResults([]);
          setActiveIndex(-1);
        })
        .finally(() => {
          if (active) setIsLoading(false);
        });
    }, 220);

    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, retryKey]);

  const openResult = (result: GlobalSearchResult) => {
    const href =
      result.type === "passport"
        ? ROUTES.dashboard.passportDetail(result.id)
        : ROUTES.dashboard.passportGroup(result.group_id ?? result.id);
    setIsOpen(false);
    setQuery("");
    setActiveIndex(-1);
    router.push(href as never);
  };

  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setIsOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (results.length === 0 || isLoading || error) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIsOpen(true);
      setActiveIndex(
        (current) => (current + 1 + results.length) % results.length,
      );
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setIsOpen(true);
      setActiveIndex(
        (current) => (current - 1 + results.length) % results.length,
      );
    } else if (event.key === "Enter" && isOpen && activeIndex >= 0) {
      event.preventDefault();
      openResult(results[activeIndex]);
    }
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-lg">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <label htmlFor={inputId} className="sr-only">
          Search passports and groups
        </label>
        <input
          ref={inputRef}
          id={inputId}
          suppressHydrationWarning
          value={query}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={isOpen && query.trim().length >= 2}
          aria-controls={listboxId}
          aria-describedby={statusId}
          aria-activedescendant={
            isOpen && activeIndex >= 0
              ? `${listboxId}-option-${activeIndex}`
              : undefined
          }
          onChange={(event) => {
            const nextQuery = event.target.value;
            setIsOpen(true);
            setQuery(nextQuery);
            setError(null);
            setResults([]);
            setActiveIndex(-1);
            if (nextQuery.trim().length < 2) {
              setResults([]);
              setIsLoading(false);
              setActiveIndex(-1);
            } else {
              setIsLoading(true);
            }
          }}
          onFocus={() => {
            if (query.trim().length >= 2) setIsOpen(true);
          }}
          onKeyDown={handleInputKeyDown}
          placeholder="Search passengers, groups..."
          title="Search passports and groups (Ctrl+K or Command+K)"
          className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-10 pr-10 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:ring-2 focus:ring-blue-100"
        />
        {query && (
          <button
            type="button"
            suppressHydrationWarning
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Clear search"
            onClick={() => {
              setQuery("");
              setResults([]);
              setIsOpen(false);
              setActiveIndex(-1);
            }}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {isOpen && query.trim().length >= 2 && (
        <div
          id={listboxId}
          role="listbox"
          aria-label="Search results"
          className="fixed left-3 right-3 top-[68px] z-50 sm:absolute sm:left-0 sm:right-0 sm:top-11 sm:min-w-[min(26rem,85vw)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl"
        >
          {isLoading ? (
            <div
              id={statusId}
              role="status"
              className="px-4 py-4 text-sm text-slate-500"
            >
              Searching...
            </div>
          ) : error ? (
            <div className="px-4 py-4 text-sm">
              <p id={statusId} role="alert" className="text-red-700">
                {error}
              </p>
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setIsLoading(true);
                  setRetryKey((value) => value + 1);
                }}
                className="mt-2 font-semibold text-blue-700"
              >
                Retry search
              </button>
            </div>
          ) : results.length === 0 ? (
            <div
              id={statusId}
              role="status"
              className="px-4 py-4 text-sm text-slate-500"
            >
              No matching passports or groups found.
            </div>
          ) : (
            <div className="max-h-96 overflow-y-auto py-2">
              <div id={statusId} role="status" className="sr-only">
                {results.length} result{results.length === 1 ? "" : "s"}{" "}
                available. Use arrow keys to review.
              </div>
              {results.map((result, index) => (
                <button
                  key={`${result.type}:${result.id}`}
                  id={`${listboxId}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={activeIndex === index}
                  tabIndex={-1}
                  className={`flex w-full items-start gap-3 px-4 py-3 text-left ${
                    activeIndex === index ? "bg-blue-50" : "hover:bg-slate-50"
                  }`}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => openResult(result)}
                >
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                    {result.type === "passport" ? (
                      <FileText className="h-4 w-4" />
                    ) : (
                      <FolderOpen className="h-4 w-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-slate-900">
                        {result.title}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium uppercase text-slate-500">
                        {result.type}
                      </span>
                    </span>
                    {result.subtitle && (
                      <span className="mt-0.5 block truncate text-xs text-slate-500">
                        {result.subtitle}
                      </span>
                    )}
                    <span className="mt-1 block truncate text-xs text-slate-400">
                      {[
                        result.client_phone,
                        result.group_name,
                        result.destination,
                      ]
                        .filter(Boolean)
                        .join(" | ")}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
