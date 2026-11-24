"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { Button, Input } from "@/components/ui";
import { WorkspacePagination } from "@/components/shared/workspace-pagination";
import { clampPageOffset } from "@/lib/utils/pagination";
import type { ManualContact } from "../types/contacts";
import { importedFieldLabel } from "../utils/imported-field-label";

export function ContactEditor({
  title,
  description,
  value,
  contacts,
  onValueChange,
  onAdd,
  onRemove,
  onContactChange,
}: {
  title: string;
  description: string;
  value: ManualContact;
  contacts: ManualContact[];
  onValueChange: Dispatch<SetStateAction<ManualContact>>;
  onAdd: () => void;
  onRemove: (index: number) => void;
  onContactChange?: (index: number, contact: ManualContact) => void;
}) {
  const [requestedOffset, setOffset] = useState(0);
  const offset = clampPageOffset(requestedOffset, contacts.length, 50);

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 p-4">
      <div>
        <h3 className="font-medium text-slate-900">{title}</h3>
        <p className="mt-1 text-xs text-slate-500">{description}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <Input
          label="Name"
          placeholder="Raman Jha"
          value={value.name}
          onChange={(event) => onValueChange((current) => ({ ...current, name: event.target.value }))}
        />
        <Input
          label="WhatsApp number"
          placeholder="+91 98187 52221"
          value={value.phone_number}
          onChange={(event) => onValueChange((current) => ({ ...current, phone_number: event.target.value }))}
        />
        <div className="flex items-end">
          <Button
            type="button"
            variant="secondary"
            disabled={!value.name.trim() || !value.phone_number.trim()}
            onClick={onAdd}
          >
            Add
          </Button>
        </div>
      </div>
      {contacts.length > 0 && (
        <div className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
          {contacts.slice(offset, offset + 50).map((contact, pageIndex) => {
            const index = offset + pageIndex;
            return (
              <div
                key={index}
                className={`gap-2 px-3 py-2 text-sm ${onContactChange
                    ? "grid items-center md:grid-cols-[1fr_1fr_auto]"
                    : "flex items-center justify-between"
                  }`}
              >
                {onContactChange ? (
                  <>
                    <Input
                      aria-label={`Recipient ${index + 1} name`}
                      value={contact.name}
                      onChange={(event) =>
                        onContactChange(index, {
                          ...contact,
                          name: event.target.value,
                        })
                      }
                    />
                    <Input
                      aria-label={`Recipient ${index + 1} WhatsApp number`}
                      value={contact.phone_number}
                      onChange={(event) =>
                        onContactChange(index, {
                          ...contact,
                          phone_number: event.target.value,
                        })
                      }
                    />
                  </>
                ) : (
                  <span className="min-w-0 truncate text-slate-700">
                    {contact.name} - {contact.phone_number}
                  </span>
                )}
                <button
                  type="button"
                  className="justify-self-end text-xs font-medium text-red-600 hover:text-red-700"
                  onClick={() => onRemove(index)}
                  aria-label={`Remove ${contact.name || `contact ${index + 1}`}`}
                >
                  Remove
                </button>
                {contact.imported_fields &&
                  Object.keys(contact.imported_fields).length > 0 && (
                    <details className="md:col-span-3">
                      <summary className="cursor-pointer text-xs font-medium text-blue-700">
                        View {Object.keys(contact.imported_fields).length} imported
                        detail
                        {Object.keys(contact.imported_fields).length === 1
                          ? ""
                          : "s"}
                      </summary>
                      <dl className="mt-2 grid gap-x-4 gap-y-2 rounded-lg bg-slate-50 p-3 sm:grid-cols-2">
                        {Object.entries(contact.imported_fields).map(
                          ([key, fieldValue]) => (
                            <div key={key} className="min-w-0">
                              <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                                {importedFieldLabel(key)}
                              </dt>
                              <dd className="truncate text-xs text-slate-700">
                                {fieldValue}
                              </dd>
                            </div>
                          ),
                        )}
                      </dl>
                    </details>
                  )}
              </div>
            );
          })}
        </div>
      )}
      {contacts.length > 50 && <WorkspacePagination total={contacts.length} offset={offset}
        limit={50} onChange={setOffset} label={title} />}
    </section>
  );
}
