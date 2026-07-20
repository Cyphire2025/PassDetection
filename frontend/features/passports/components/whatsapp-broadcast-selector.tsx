"use client";

import { Check, Loader2, MessageCircle, Search } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { useWhatsAppBroadcastOptions } from "../hooks/use-upload-links";

const MAX_LINKED_BROADCASTS = 50;

interface WhatsAppBroadcastSelectorProps {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  groupId?: string;
  title?: string;
  description?: string;
}

export function WhatsAppBroadcastSelector({
  selectedIds,
  onChange,
  disabled = false,
  groupId,
  title = "Link existing WhatsApp broadcasts",
  description = "Choose one or more recipient lists to compare with passport submissions.",
}: WhatsAppBroadcastSelectorProps) {
  const [search, setSearch] = useState("");
  const titleId = useId();
  const {
    data: broadcasts = [],
    isLoading,
    error,
  } = useWhatsAppBroadcastOptions(groupId);
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const visibleBroadcasts = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) return broadcasts;
    return broadcasts.filter((broadcast) => (
      broadcast.name.toLocaleLowerCase().includes(query)
    ));
  }, [broadcasts, search]);

  const toggle = (id: string) => {
    if (disabled) return;
    if (selected.has(id)) {
      onChange(selectedIds.filter((selectedId) => selectedId !== id));
      return;
    }
    if (selectedIds.length >= MAX_LINKED_BROADCASTS) return;
    onChange([...selectedIds, id]);
  };

  return (
    <section
      aria-labelledby={titleId}
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white"
    >
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3
              id={titleId}
              className="font-semibold text-slate-900"
            >
              {title}
            </h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
          </div>
          <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-800">
            {selectedIds.length} selected
          </span>
        </div>
        <div className="relative mt-4">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400"
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search WhatsApp broadcasts"
            aria-label="Search WhatsApp broadcasts"
            className="pl-9"
            disabled={disabled}
          />
        </div>
      </div>

      <div className="max-h-72 overflow-y-auto p-3 sm:p-4">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading WhatsApp broadcasts
          </div>
        ) : error ? (
          <div role="alert" className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
            WhatsApp broadcasts could not be loaded.
          </div>
        ) : visibleBroadcasts.length === 0 ? (
          <div className="py-10 text-center text-sm text-slate-500">
            {broadcasts.length === 0
              ? "Create a WhatsApp broadcast first, then return here to link it."
              : "No WhatsApp broadcasts match this search."}
          </div>
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {visibleBroadcasts.map((broadcast) => {
              const isSelected = selected.has(broadcast.id);
              const atLimit = selectedIds.length >= MAX_LINKED_BROADCASTS && !isSelected;
              return (
                <button
                  key={broadcast.id}
                  type="button"
                  role="checkbox"
                  aria-checked={isSelected}
                  disabled={disabled || atLimit}
                  onClick={() => toggle(broadcast.id)}
                  className={`flex min-h-20 items-center gap-3 rounded-xl border p-3 text-left transition ${
                    isSelected
                      ? "border-blue-300 bg-blue-50 ring-1 ring-blue-100"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  } disabled:cursor-not-allowed disabled:opacity-50`}
                >
                  <span
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                      isSelected ? "bg-blue-600 text-white" : "bg-emerald-50 text-emerald-700"
                    }`}
                  >
                    {isSelected
                      ? <Check className="h-4 w-4" aria-hidden="true" />
                      : <MessageCircle className="h-4 w-4" aria-hidden="true" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-slate-900">
                      {broadcast.name}
                    </span>
                    <span className="mt-1 block text-xs text-slate-500">
                      {broadcast.recipient_count.toLocaleString()} recipient
                      {broadcast.recipient_count === 1 ? "" : "s"}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {selectedIds.length >= MAX_LINKED_BROADCASTS && (
        <p role="status" className="border-t border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
          A group can link up to {MAX_LINKED_BROADCASTS} WhatsApp broadcasts.
        </p>
      )}
    </section>
  );
}
