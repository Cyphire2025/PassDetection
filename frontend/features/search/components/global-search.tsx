"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, FolderOpen, Search, X } from "lucide-react";
import { ROUTES } from "@/constants/routes";
import { searchApi, type GlobalSearchResult } from "../api/search.api";

export function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      return;
    }

    let active = true;
    const timer = window.setTimeout(() => {
      searchApi
        .global(trimmed)
        .then((items) => {
          if (!active) return;
          setResults(items);
          setIsOpen(true);
        })
        .catch(() => {
          if (!active) return;
          setResults([]);
          setIsOpen(true);
        })
        .finally(() => {
          if (active) setIsLoading(false);
        });
    }, 220);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  const openResult = (result: GlobalSearchResult) => {
    const href = result.type === "passport"
      ? ROUTES.dashboard.passportDetail(result.id)
      : ROUTES.dashboard.passportGroup(result.group_id ?? result.id);
    setIsOpen(false);
    setQuery("");
    router.push(href as never);
  };

  return (
    <div ref={containerRef} className="relative hidden w-full max-w-xl md:block">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          suppressHydrationWarning
          value={query}
          onChange={(event) => {
            const nextQuery = event.target.value;
            setQuery(nextQuery);
            if (nextQuery.trim().length < 2) {
              setResults([]);
              setIsLoading(false);
            } else {
              setIsLoading(true);
            }
            setIsOpen(true);
          }}
          onFocus={() => {
            if (query.trim().length >= 2) setIsOpen(true);
          }}
          placeholder="Search passport number, name, mobile, email, destination, group"
          className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 pl-10 pr-10 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:ring-2 focus:ring-blue-100"
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
            }}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {isOpen && query.trim().length >= 2 && (
        <div className="absolute left-0 right-0 top-12 z-50 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          {isLoading ? (
            <div className="px-4 py-4 text-sm text-slate-500">Searching...</div>
          ) : results.length === 0 ? (
            <div className="px-4 py-4 text-sm text-slate-500">No matching passports or groups found.</div>
          ) : (
            <div className="max-h-96 overflow-y-auto py-2">
              {results.map((result) => (
                <button
                  key={`${result.type}:${result.id}`}
                  type="button"
                  className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50"
                  onClick={() => openResult(result)}
                >
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                    {result.type === "passport" ? <FileText className="h-4 w-4" /> : <FolderOpen className="h-4 w-4" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-slate-900">{result.title}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium uppercase text-slate-500">
                        {result.type}
                      </span>
                    </span>
                    {result.subtitle && <span className="mt-0.5 block truncate text-xs text-slate-500">{result.subtitle}</span>}
                    <span className="mt-1 block truncate text-xs text-slate-400">
                      {[result.client_phone, result.group_name, result.destination].filter(Boolean).join(" | ")}
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
