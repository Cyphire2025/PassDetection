"use client";

import { ListChecks, Search, ShieldCheck } from "lucide-react";
import { useDeferredValue, useId, useState } from "react";
import type {
  LinkedWhatsAppBroadcast,
  WhatsAppMatchFieldOption,
} from "../api/upload-links.api";

export type WhatsAppMatchingFieldsByBroadcast = Record<string, string[]>;

export const MAX_MATCHING_FIELDS_PER_BROADCAST = 32;

const PREFERRED_NAME_FIELDS = new Set([
  "name",
  "full name",
  "customer name",
  "client name",
  "passenger name",
  "participant name",
]);
const PREFERRED_PHONE_FIELDS = new Set([
  "mobile",
  "mobile no",
  "mobile number",
  "phone",
  "phone no",
  "phone number",
  "whatsapp",
  "whatsapp no",
  "whatsapp number",
]);

interface WhatsAppMatchFieldSelectorProps {
  broadcasts: LinkedWhatsAppBroadcast[];
  selectedMatchingFields: WhatsAppMatchingFieldsByBroadcast;
  onChange: (fields: WhatsAppMatchingFieldsByBroadcast) => void;
  disabled?: boolean;
}

function normalizedFieldName(value: string): string {
  return value
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function preferredNameField(field: WhatsAppMatchFieldOption): boolean {
  return PREFERRED_NAME_FIELDS.has(normalizedFieldName(field.key))
    || PREFERRED_NAME_FIELDS.has(normalizedFieldName(field.label));
}

function preferredPhoneField(field: WhatsAppMatchFieldOption): boolean {
  return PREFERRED_PHONE_FIELDS.has(normalizedFieldName(field.key))
    || PREFERRED_PHONE_FIELDS.has(normalizedFieldName(field.label));
}

/** Preserve familiar matching for a newly linked broadcast without selecting risky fields. */
export function recommendedMatchingFieldKeys(
  fields: WhatsAppMatchFieldOption[],
): string[] {
  const name = fields.find(preferredNameField)?.key;
  const phone = fields.find(preferredPhoneField)?.key;
  const preferred = Array.from(new Set([name, phone].filter(Boolean))) as string[];
  return preferred;
}

function displayFields(
  broadcast: LinkedWhatsAppBroadcast,
  selectedKeys: string[],
): WhatsAppMatchFieldOption[] {
  const fields = [...(broadcast.available_matching_fields ?? [])];
  const knownKeys = new Set(fields.map((field) => field.key));
  for (const key of selectedKeys) {
    if (knownKeys.has(key)) continue;
    fields.push({ key, label: fieldLabel(key) });
  }
  return fields;
}

function fieldLabel(key: string): string {
  return key
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toLocaleUpperCase() + part.slice(1))
    .join(" ");
}

export function broadcastMatchingSummary(
  broadcast: LinkedWhatsAppBroadcast,
): string {
  if (!broadcast.matching_field_keys?.length) return "Legacy smart matching";
  const labelsByKey = new Map(
    (broadcast.available_matching_fields ?? []).map((field) => [field.key, field.label]),
  );
  return `Match by ${broadcast.matching_field_keys.map(
    (key) => labelsByKey.get(key) ?? fieldLabel(key),
  ).join(" or ")}`;
}

export function WhatsAppMatchFieldSelector({
  broadcasts,
  selectedMatchingFields,
  onChange,
  disabled = false,
}: WhatsAppMatchFieldSelectorProps) {
  const titleId = useId();
  const searchId = useId();
  const [fieldSearch, setFieldSearch] = useState("");
  const deferredFieldSearch = useDeferredValue(
    fieldSearch.trim().toLocaleLowerCase(),
  );
  if (broadcasts.length === 0) return null;

  const updateBroadcastFields = (
    broadcastId: string,
    nextKeys: string[],
  ) => {
    onChange({
      ...selectedMatchingFields,
      [broadcastId]: nextKeys,
    });
  };

  return (
    <section
      aria-labelledby={titleId}
      className="overflow-hidden rounded-2xl border border-blue-200 bg-blue-50/40"
    >
      <div className="border-b border-blue-100 bg-white/80 px-4 py-4 sm:px-5">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-100 text-blue-700">
            <ListChecks className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h4 id={titleId} className="text-sm font-semibold text-slate-900">
              Choose identification fields
            </h4>
            <p className="mt-1 text-xs leading-5 text-slate-600">
              Every imported Excel heading is available. A submission is identified when
              <strong className="font-semibold text-slate-800"> any one </strong>
              selected value matches, even if the other selected values differ.
            </p>
          </div>
        </div>
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-900">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>
            If a value points to more than one person, it stays in Needs review instead of
            being assigned automatically.
          </p>
        </div>
        <label htmlFor={searchId} className="mt-3 block text-xs font-semibold text-slate-700">
          Search spreadsheet headings
        </label>
        <div className="relative mt-1.5">
          <Search
            className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400"
            aria-hidden="true"
          />
          <input
            id={searchId}
            type="search"
            value={fieldSearch}
            disabled={disabled}
            onChange={(event) => setFieldSearch(event.target.value)}
            placeholder="e.g. Producer Code or Location"
            className="h-9 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100"
          />
        </div>
      </div>

      <div className="max-h-80 space-y-3 overflow-y-auto p-3 sm:p-4">
        {broadcasts.map((broadcast) => {
          const hasControlledSelection = Object.prototype.hasOwnProperty.call(
            selectedMatchingFields,
            broadcast.id,
          );
          const selectedKeys = hasControlledSelection
            ? selectedMatchingFields[broadcast.id] ?? []
            : broadcast.matching_field_keys ?? [];
          const fields = displayFields(broadcast, selectedKeys);
          const visibleFields = deferredFieldSearch
            ? fields.filter((field) => (
                `${field.label} ${field.key}`.toLocaleLowerCase().includes(deferredFieldSearch)
              ))
            : fields;
          const selectedKeySet = new Set(selectedKeys);
          const selectionAtLimit = selectedKeys.length >= MAX_MATCHING_FIELDS_PER_BROADCAST;
          const usesLegacyMatching = !hasControlledSelection
            && broadcast.matching_field_keys == null;

          return (
            <fieldset
              key={broadcast.id}
              className="min-w-0 rounded-xl border border-slate-200 bg-white p-3.5"
              disabled={disabled}
            >
              <legend className="sr-only">Identification fields for {broadcast.name}</legend>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-900">
                    {broadcast.name}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {fields.length.toLocaleString()} spreadsheet heading
                    {fields.length === 1 ? "" : "s"}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                  selectedKeys.length > 0
                    ? "bg-blue-100 text-blue-800"
                    : "bg-amber-100 text-amber-800"
                }`}>
                  {selectedKeys.length > 0
                    ? `${selectedKeys.length} / ${MAX_MATCHING_FIELDS_PER_BROADCAST} selected`
                    : "Legacy matching"}
                </span>
              </div>

              {fields.length === 0 ? (
                <p className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-3 text-xs leading-5 text-slate-600">
                  No matchable spreadsheet headings are stored for this broadcast yet.
                  Re-import a roster with headings to configure identification fields.
                </p>
              ) : visibleFields.length === 0 ? (
                <p className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-3 text-xs leading-5 text-slate-600">
                  No headings in this broadcast match “{fieldSearch.trim()}”.
                </p>
              ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                  {visibleFields.map((field) => {
                    const checked = selectedKeySet.has(field.key);
                    const isOnlySelection = checked && selectedKeys.length === 1;
                    const isBlockedByLimit = !checked && selectionAtLimit;
                    return (
                      <label
                        key={field.key}
                        title={field.key === field.label ? undefined : `Stored as ${field.key}`}
                        className={`inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition ${
                          checked
                            ? "border-blue-300 bg-blue-50 text-blue-900"
                            : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                        } ${disabled || isOnlySelection || isBlockedByLimit ? "cursor-not-allowed opacity-70" : "cursor-pointer"}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled || isOnlySelection || isBlockedByLimit}
                          onChange={(event) => {
                            const nextKeys = event.target.checked
                              ? [...selectedKeys, field.key]
                              : selectedKeys.filter((key) => key !== field.key);
                            updateBroadcastFields(broadcast.id, Array.from(new Set(nextKeys)));
                          }}
                          className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                        />
                        <span>{field.label}</span>
                      </label>
                    );
                  })}
                </div>
              )}

              {selectionAtLimit && (
                <p role="status" className="mt-3 text-xs leading-5 text-amber-700">
                  Maximum {MAX_MATCHING_FIELDS_PER_BROADCAST} fields selected. Deselect one
                  before choosing another heading.
                </p>
              )}

              {usesLegacyMatching && fields.length > 0 ? (
                <p className="mt-3 text-xs leading-5 text-amber-700">
                  Existing smart matching remains active until you choose a heading.
                </p>
              ) : selectedKeys.length > 0 ? (
                <p className="mt-3 text-xs leading-5 text-slate-500">
                  Match by {selectedKeys.map((key) => (
                    fields.find((field) => field.key === key)?.label ?? fieldLabel(key)
                  )).join(" or ")}. At least one field must stay selected.
                </p>
              ) : null}
            </fieldset>
          );
        })}
      </div>
    </section>
  );
}
