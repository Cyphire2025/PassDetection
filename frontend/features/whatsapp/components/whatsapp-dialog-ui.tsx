"use client";

import { X } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { Button, Card, CardContent, Input } from "@/components/ui";

export type ManualContact = {
  name: string;
  phone_number: string;
};

export function ContactEditor({
  title,
  description,
  value,
  contacts,
  onValueChange,
  onAdd,
  onRemove,
}: {
  title: string;
  description: string;
  value: ManualContact;
  contacts: ManualContact[];
  onValueChange: Dispatch<SetStateAction<ManualContact>>;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
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
          <Button type="button" variant="secondary" onClick={onAdd}>Add</Button>
        </div>
      </div>
      {contacts.length > 0 && (
        <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {contacts.map((contact, index) => (
            <div key={`${contact.phone_number}-${index}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 truncate text-slate-700">
                {contact.name} - {contact.phone_number}
              </span>
              <button
                type="button"
                className="text-xs font-medium text-red-600 hover:text-red-700"
                onClick={() => onRemove(index)}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function DialogFrame({
  title,
  onClose,
  widthClass = "max-w-3xl",
  children,
}: {
  title: string;
  onClose: () => void;
  widthClass?: string;
  children: ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card className={`max-h-[92vh] w-full overflow-auto shadow-2xl ${widthClass}`}>
        <CardContent className="p-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
            <button
              type="button"
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              onClick={onClose}
              aria-label="Close dialog"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          {children}
        </CardContent>
      </Card>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{message}</div>;
}

export function readErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "response" in error) {
    const response = (error as {
      response?: { data?: { detail?: unknown; message?: unknown } };
    }).response;
    const detail = response?.data?.detail ?? response?.data?.message;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : ""
        ))
        .filter(Boolean);
      if (messages.length > 0) return messages.join(" ");
    }
  }
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
